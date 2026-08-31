#!/usr/bin/env bash
# Local test launcher. Uses throwaway credentials — never use these in a deployment.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

export SECRET_KEY="dev-secret-key"
export SIGNUP_TOKEN="dev-signup-token"
export ADMIN_PASSWORD="admin"

DATA_FILE="${DATA_FILE:-data/eval_instances.jsonl}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5001}"

if [[ ! -f "$DATA_FILE" ]]; then
    echo "Comparison data file not found: $DATA_FILE" >&2
    exit 1
fi

echo "Data file:      $DATA_FILE"
echo "Signup token:   $SIGNUP_TOKEN"
# The admin account is only created on the very first run, before evaluation.db exists
echo "Admin login:    admin / $ADMIN_PASSWORD"
echo "URL:            http://${HOST}:${PORT}"
echo

exec python app.py \
    --comparison_data_path "$DATA_FILE" \
    --host "$HOST" \
    --port "$PORT" \
    "$@"
