#!/usr/bin/env bash
set -euo pipefail

# One-command local run for ReceiptGate (development)
# Requires dependencies installed (pip install -e .)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export RECEIPTGATE_ALLOW_INSECURE_DEV="true"
export RECEIPTGATE_AUTO_MIGRATE_ON_STARTUP="true"
export PYTHONPATH="$SCRIPT_DIR/src"

python -m receiptgate.main
