#!/bin/bash
set -e

# Change directory to project root
cd "$(dirname "$0")/.."

echo "=== 1. Running Ruff Linter & Formatter ==="
if command -v ruff &> /dev/null; then
    ruff check app tests scripts
    ruff format --check app tests scripts
else
    if [ -f "./venv/bin/ruff" ]; then
        ./venv/bin/ruff check app tests scripts
        ./venv/bin/ruff format --check app tests scripts
    else
        echo "Ruff is not installed, skipping formatting/linting checks."
    fi
fi

echo "=== 2. Running Pytest Suite ==="
./venv/bin/pytest tests/

echo "=== 3. Checking Database Migrations (SQLite) ==="
rm -f instance/test_ci.db
DATABASE_URL="sqlite:///test_ci.db" ./venv/bin/flask db upgrade
rm -f instance/test_ci.db

echo "=== 4. Running Dependency Audit ==="
if [ -f "./venv/bin/pip-audit" ]; then
    ./venv/bin/pip-audit
elif [ -f "./venv/bin/safety" ]; then
    ./venv/bin/safety check
else
    echo "pip-audit or safety is not installed, skipping dependency vulnerability check."
fi

echo "🎉 All CI checks passed successfully!"
