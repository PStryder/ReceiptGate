# One-command local run for ReceiptGate (development)
# Requires dependencies installed (pip install -e .)

$env:RECEIPTGATE_ALLOW_INSECURE_DEV = "true"
$env:RECEIPTGATE_AUTO_MIGRATE_ON_STARTUP = "true"
$env:PYTHONPATH = "$PSScriptRoot\src"

python -m receiptgate.main
