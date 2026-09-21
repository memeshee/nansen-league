# Deploy (Fly.io, canonical)

- App: `smart-money-league` (org Kiter), region `sin`,
  https://smart-money-league.fly.dev/
- One shared-cpu-1x/512MB machine runs bot + dashboard via `start.sh`.
- Volume `league_data` (1GB) mounted at `/data`; `start.sh` symlinks
  `league.db`, `.nansen_cache`, `.spend_log.jsonl` into `/app`.
- Secrets (`fly secrets set -a smart-money-league`):
  `NANSEN_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TYPESAFE_API_KEY`,
  `TELEGRAM_BOT_USERNAME`. Values live only in Fly + local `.env` (gitignored).
- Local systemd units (`nansen-league`, `leaguedesk`, `leaguedesk-tunnel`)
  are DISABLED — running the local bot alongside Fly causes Telegram
  getUpdates 409 Conflict. Never run both.
- `FLY_ACCESS_TOKEN` is in local `.env` (gitignored). Export it for CLI use:
  `export FLY_ACCESS_TOKEN=$(sed -n 's/^FLY_ACCESS_TOKEN=//p' .env)`
  (plain `cut -d= -f2` TRUNCATES the token at `=` padding — always use sed).
- Useful: `fly logs -a smart-money-league -n`,
  `fly ssh console -a smart-money-league`, `fly deploy` from this dir.
