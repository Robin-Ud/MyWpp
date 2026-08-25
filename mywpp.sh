#!/usr/bin/env bash
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
DIR="$(cd "$(dirname "$SELF")" && pwd)"
exec python3 "$DIR/mywpp.py" "$@"
