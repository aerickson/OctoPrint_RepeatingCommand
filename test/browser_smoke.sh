#!/usr/bin/env bash

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_root="$repo_root/.tmp/octoprint-smoke-runtime"
basedir="$repo_root/.tmp/octoprint-smoke"
artifacts="$repo_root/.tmp/octoprint-smoke-artifacts"
venv="$runtime_root/venv"
browser_cache="$runtime_root/browsers"
uv_cache="${TMPDIR:-/tmp}/octoprint-repeatingcommand-uv-cache"
wheel_dir="$runtime_root/dist"
server_log="$artifacts/octoprint.log"

preserve_basedir=false
headed=false
verbose=false

usage() {
    cat <<'EOF'
Usage: test/browser_smoke.sh [OPTIONS]

Run the Repeating Command settings smoke test against a temporary OctoPrint
instance using system Firefox.

Options:
  --preserve-basedir  Keep the existing OctoPrint basedir instead of resetting it.
  --headed            Show the Firefox window while the test runs.
  --verbose           Stream the OctoPrint server log to the terminal.
  -h, --help          Show this help.
EOF
}

while (($#)); do
    case "$1" in
        --preserve-basedir) preserve_basedir=true ;;
        --headed) headed=true ;;
        --verbose) verbose=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is required; install it from https://docs.astral.sh/uv/" >&2
    exit 1
fi

mkdir -p "$repo_root/.tmp" "$artifacts"
if [[ "$preserve_basedir" != true ]]; then
    rm -rf "$basedir"
fi
mkdir -p "$basedir"
if [[ ! -f "$basedir/config.yaml" ]]; then
    cp "$repo_root/test/browser_smoke_config.yaml" "$basedir/config.yaml"
fi
rm -rf "$runtime_root"
mkdir -p "$wheel_dir"

cleanup() {
    status=$?
    if [[ -n "${server_pid:-}" ]] && kill -0 "$server_pid" 2>/dev/null; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf "$runtime_root"
    if [[ "$status" -ne 0 && -f "$server_log" ]]; then
        echo >&2
        echo "Last OctoPrint log lines:" >&2
        tail -n 80 "$server_log" >&2 || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

echo "Building plugin wheel..."
UV_CACHE_DIR="$uv_cache" uv build --wheel --out-dir "$wheel_dir" >/dev/null
wheel_path=$(find "$wheel_dir" -maxdepth 1 -type f -name '*.whl' -print -quit)
if [[ -z "$wheel_path" ]]; then
    echo "error: uv build did not produce a wheel" >&2
    exit 1
fi

echo "Creating temporary Python environment..."
UV_CACHE_DIR="$uv_cache" uv venv --python 3.11 --seed "$venv" >/dev/null
python_path="$venv/bin/python"

echo "Installing OctoPrint, browser dependencies, and plugin wheel..."
UV_CACHE_DIR="$uv_cache" uv pip install --python "$python_path" \
    --group playwright-testing \
    --upgrade-package octoprint \
    octoprint "$wheel_path" >/dev/null

if [[ ! -f "$basedir/users.yaml" ]]; then
    "$venv/bin/octoprint" -b "$basedir" user add smoke-admin \
        --password smoke-password --admin >/dev/null
fi

echo "Installing Playwright Firefox..."
PLAYWRIGHT_BROWSERS_PATH="$browser_cache" "$python_path" -m playwright install firefox >/dev/null

port=$(
    "$python_path" - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)

: > "$server_log"
echo "Starting OctoPrint on http://127.0.0.1:$port ..."
(
    exec "$venv/bin/octoprint" serve \
        --basedir "$basedir" \
        --host 127.0.0.1 \
        --port "$port" \
        --iknowwhatimdoing
) >"$server_log" 2>&1 &
server_pid=$!

if [[ "$verbose" == true ]]; then
    tail -f "$server_log" &
    log_tail_pid=$!
fi

stop_log_tail() {
    if [[ -n "${log_tail_pid:-}" ]] && kill -0 "$log_tail_pid" 2>/dev/null; then
        kill "$log_tail_pid" 2>/dev/null || true
        wait "$log_tail_pid" 2>/dev/null || true
    fi
}
trap 'stop_log_tail; cleanup' EXIT INT TERM

echo "Waiting for OctoPrint..."
for attempt in {1..60}; do
    if curl -fsS "http://127.0.0.1:$port/" >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
        echo "error: OctoPrint exited before becoming ready" >&2
        exit 1
    fi
    sleep 1
    if [[ "$attempt" -eq 60 ]]; then
        echo "error: OctoPrint did not become ready within 60 seconds" >&2
        exit 1
    fi
done

test_args=("--base-url" "http://127.0.0.1:$port" "--artifacts" "$artifacts")
if [[ "$headed" == true ]]; then
    test_args+=("--headed")
fi

echo "Running browser smoke test..."
PLAYWRIGHT_BROWSERS_PATH="$browser_cache" "$python_path" "$repo_root/test/browser_smoke.py" "${test_args[@]}"
echo "Browser smoke test passed."
