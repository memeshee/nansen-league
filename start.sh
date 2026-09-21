#!/bin/bash
# One machine runs both processes; state lives on the /data volume.
set -e
mkdir -p /data
# Targets must exist BEFORE symlinking: makedirs(exist_ok=True) raises
# FileExists on a dangling symlink (fresh volume) — seen live as
# "/deep failed: [Errno 17] File exists: '/app/.nansen_cache'".
mkdir -p /data/nansen_cache
touch /data/spend_log.jsonl /data/league.db
ln -sfn /data/league.db /app/league.db
ln -sfn /data/nansen_cache /app/.nansen_cache
ln -sfn /data/spend_log.jsonl /app/.spend_log.jsonl
python dashboard.py &
python bot.py &
wait -n
