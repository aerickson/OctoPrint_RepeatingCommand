#!/usr/bin/env bash

set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv run pytest -q
    uv run python -m py_compile octoprint_repeatingcommand/__init__.py
    uv run python test/jinja_syntax_check.py
else
    python -m pytest -q
    python -m py_compile octoprint_repeatingcommand/__init__.py
    python test/jinja_syntax_check.py
fi

node test/repeatingcommand_viewmodel_smoke.js
node --check octoprint_repeatingcommand/static/js/repeatingcommand.js

echo "All tests passed."
