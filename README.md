# Fantasy Smart Money League + Due-Diligence Copilot

Nansen Meridian Buildathon entry. Telegram bot where you draft proven
smart-money wallets into weekly rounds, settled on live Nansen PnL data —
plus a token due-diligence copilot with teeth.

## Architecture: Nansen data → Jev triage/verdicts → Telegram game

LLMs only do deep dives. Everything real-time is a typed Jev judgment:

1. **Verdicts in <1s.** `/check` turns smart-money flow into a typed Jev
   Score with calibrated confidence — no slow LLM essay.
2. **Credit guard.** Every Nansen call burns credits. Jev triages first
   (1-credit glance vs 5-credit deep dive), so the bot stops bleeding API
   budget on noise. It pays for itself.
3. **Escalation ladder.** High confidence → act. Guard near 0.5 or verdict
   confidence < 0.5 → escalate to a full LLM teardown. Uncertainty drives
   the split — that's what calibrated probabilities are for.

## Verified live

- `smart-money-pnl-leaderboard` (5cr): real wallets, realized+unrealized
  PnL, win rate, trade counts — the league's settlement source.
- `token flows` / `flow-intelligence` (1cr), `token pnl` (5cr): structure
  verified; coverage varies by token (thin for JUP, manage expectations).
- Jev `jev-latest` (1.13.0): Score + Noul batch in one request, ~0.1s.
- NOTE: Score questions take **`criteria`** (array of level descriptions),
  not `levels` — the 422 error tells you. CLI only supports Solana well;
  Ethereum token calls hang, so the bot defaults to Solana.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill NANSEN_API_KEY + TELEGRAM_BOT_TOKEN
python bot.py
```

Commands: `/start /check <mint> [chain] /board /draft <wallet> /picks /settle`

Budgets: per-action caps (glance 1cr, deep 6cr, settle 5cr), 60cr/day hard
stop, 10-min cache so re-renders don't re-burn. Spend logged to
`.spend_log.jsonl`. State in `league.db`. `.env` is git-ignored, never
committed — keys also live in `~/.config/typesafe/api_key` (600).
