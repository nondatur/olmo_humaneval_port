#!/usr/bin/env bash
# Local test launcher running gunicorn like the container does.
# Uses throwaway credentials — never use these in a deployment.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

export SECRET_KEY="dev-secret-key"
export SIGNUP_TOKEN="dev-signup-token"
export ADMIN_PASSWORD="admin"

# Matches the container default so local runs mirror the deployment
DATA_FILE="${DATA_FILE:-data/eval_instances.jsonl}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5001}"
WORKERS="${WORKERS:-1}"
THREADS="${THREADS:-8}"

if [[ ! -f "$DATA_FILE" ]]; then
    echo "Comparison data file not found: $DATA_FILE" >&2
    exit 1
fi

# gunicorn imports the app instead of calling main(), so the data file is passed in the environment
export COMPARISON_DATA_PATH="$DATA_FILE"

# An activated virtualenv wins over the repo's .venv, which may not be the one in use
if [[ -n "${PYTHON:-}" ]]; then
    :
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
elif [[ -x .venv/bin/python ]]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python"
fi

if ! "$PYTHON" -c "import gunicorn" >/dev/null 2>&1; then
    echo "gunicorn is not available for $PYTHON." >&2
    echo "Install it with: $PYTHON -m pip install -r requirements.txt" >&2
    exit 1
fi

echo "Interpreter:    $PYTHON"
echo "Data file:      $DATA_FILE"
echo "Signup token:   $SIGNUP_TOKEN"
echo "Admin login:    admin / $ADMIN_PASSWORD"
echo "URL:            http://${HOST}:${PORT}"

# Keep --workers at 1 to match production: one writer only, see README
exec "$PYTHON" -m gunicorn \
    --bind "${HOST}:${PORT}" \
    --workers "$WORKERS" \
    --threads "$THREADS" \
    --timeout 120 \
    --access-logfile - \
    "$@" \
    app:app
