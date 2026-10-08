#!/usr/bin/env sh
# Daily backup of the agent's database (investigations, decisions, incident memory).
# On the server, from cron: 0 4 * * * cd ~/Incilot && make backup
# Keeps the last 14 days in backups/.
set -eu
mkdir -p backups
file="backups/agent_state-$(date +%F).sql.gz"
docker compose exec -T postgres pg_dump -U incilot agent_state | gzip > "$file"
find backups -name 'agent_state-*.sql.gz' -mtime +14 -delete
echo "saved $file"
