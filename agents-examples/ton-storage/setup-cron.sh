#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_ENTRY="*/30 * * * * cd ${SCRIPT_DIR} && python cleanup.py >> ${SCRIPT_DIR}/cleanup.log 2>&1"

# Remove old entry if exists, then add new one
(crontab -l 2>/dev/null | grep -v "ton-storage.*cleanup.py" || true; echo "$CRON_ENTRY") | crontab -

echo "Cron job installed: ${CRON_ENTRY}"
