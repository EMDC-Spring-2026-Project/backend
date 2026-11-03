#!/bin/bash
# Script to create an admin account in Docker
# Usage: ./create_admin.sh [username] [first_name] [last_name]

set -euo pipefail

cd /backend

if (( $# > 3 )); then
    echo "Usage: $0 [username] [first_name] [last_name]" >&2
    exit 2
fi

USERNAME=${1:-}
FIRST_NAME=${2:-"Admin"}
LAST_NAME=${3:-"User"}

echo "Creating admin account..."
echo "Name: $FIRST_NAME $LAST_NAME"

COMMAND=(python manage.py create_first_admin)
if [[ -n "$USERNAME" ]]; then
    COMMAND+=(--username "$USERNAME")
fi
"${COMMAND[@]}" \
    --first-name "$FIRST_NAME" \
    --last-name "$LAST_NAME"

echo "✓ Admin account command completed."

