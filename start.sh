#!/bin/bash
# One machine runs both processes; state lives on the /data volume.
set -e
mkdir -p /data
ln -sfn /data/league.db /app/league.db
ln -sfn /data/nansen_cache /app/.nansen_cache
ln -sfn /data/spend_log.jsonl /app/.spend_log.jsonl
python dashboard.py &
python bot.py &
wait -n
