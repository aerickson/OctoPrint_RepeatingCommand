#!/usr/bin/env bash

set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    python_runner=(uv run python)
    pytest_runner=(uv run pytest)
else
    python_runner=(python)
    pytest_runner=(python -m pytest)
fi

printf '\n== Backend unit tests ==\n'
"${pytest_runner[@]}" -q test/test_repeatingcommand.py

printf '\n== Package and plugin metadata tests ==\n'
"${pytest_runner[@]}" -q test/test_package.py

printf '\n== Python syntax checks ==\n'
"${python_runner[@]}" -m py_compile octoprint_repeatingcommand/__init__.py
"${python_runner[@]}" test/jinja_syntax_check.py

printf '\n== Frontend viewmodel tests ==\n'
node test/repeatingcommand_viewmodel_smoke.js

printf '\n== JavaScript syntax checks ==\n'
node --check octoprint_repeatingcommand/static/js/repeatingcommand.js

printf '\nAll tests passed.\n'
