"""Fantasy Smart Money league + due-diligence copilot Telegram bot.

Pipeline per /check: Jev guard (spend?) -> Nansen (budget-capped) -> Jev verdict.
Escalation ladder: high confidence -> verdict stands; ~0.5 -> LLM teardown flag.
"""
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import jev
import league
import nansen_client

log = logging.getLogger(__name__)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    await update.message.reply_text(
        "Fantasy Smart Money League.\n"
        "/check <mint> [chain] — due-diligence verdict on a token\n"
        "/board — top smart-money wallets this week (5cr, cached 10m)\n"
        "/draft <wallet> — draft a wallet into this week's round\n"
        "/picks — your current picks\n"
        "/settle — settle the round on live PnL (anyone can trigger)"
    )


async def check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    if not ctx.args:
        await update.message.reply_text("Usage: /check <mint> [chain=solana]")
        return
    mint, chain = ctx.args[0], (ctx.args[1] if len(ctx.args) > 1 else "solana")
    status = await update.message.reply_text("Jev triaging…")

    # 1. Jev guard FIRST — decides glance (1cr) vs deep (5cr) vs escalate.
    # Cheap pre-state only; no Nansen spend yet.
    triage = jev.triage_token(
        {
            "token": mint,
            "chain": chain,
            "smart_money_netflow_7d_usd": 0,
            "smart_money_buyers": 0,
            "smart_money_sellers": 0,
            "top10_holder_concentration": 0.5,
            "narrative": f"Telegram user requested due diligence on {mint} ({chain}); no flow data yet, deciding how deep to look.",
        }
    )
    plan = triage["plan"]
    if plan == "escalate":
        await status.edit_text(
            f"Jev is unsure (guard {triage['guard_p']:.2f}, conf {triage['confidence']:.2f}) — "
            "flagged for full LLM teardown, running a cheap 1cr glance meanwhile."
        )
        plan = "glance"

    # 2. Nansen behind the budget guard.
    flows = nansen_client.token_flows(mint, chain, plan="glance")
    pnl = None
    if plan == "deep":
        pnl = nansen_client.token_pnl(mint, chain)

    if not flows["ok"] and (pnl is None or not pnl["ok"]):
        err = flows.get("error", "unknown")
        await status.edit_text(f"Nansen call blocked: {err}")
        return

    # 3. Jev verdict over REAL data.
    flow_rows = (flows.get("data") or {}).get("data", []) if flows.get("ok") else []
    verdict = jev.judge(
        {"token": mint, "chain": chain, "flows": flow_rows[:5],
         "pnl": ((pnl.get("data") or {}).get("data", [])[:5] if pnl and pnl.get("ok") else [])},
        {"bullishness": {"type": "score", "instructions": "How bullish is this token's smart-money flow?",
                         "criteria": jev.BULLISH_CRITERIA}},
    )["answers"]["bullishness"]

    spent = (flows.get("credits", 0) if flows.get("ok") and not flows.get("cached") else 0) + (
        pnl.get("credits", 0) if pnl and pnl.get("ok") and not pnl.get("cached") else 0
    )
    label = "BULLISH" if verdict["score"] >= 1.33 else ("BEARISH" if verdict["score"] <= 0.67 else "NEUTRAL")
    extra = "" if verdict.get("confidence", 0) >= jev.VERDICT_MIN_CONF else "\nLow confidence — escalate to LLM teardown before acting."
    await status.edit_text(
        f"{mint} ({chain}): {label} — Jev score {verdict['score']:.2f}, conf {verdict.get('confidence', 0):.2f}"
        f" (plan {triage['plan']}, guard {triage['guard_p']:.2f}, spent {spent}cr){extra}"
    )


async def board(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    status = await update.message.reply_text("Pulling smart-money leaderboard (5cr)…")
    res = nansen_client.sm_leaderboard()
    if not res["ok"]:
        await status.edit_text(f"Blocked: {res['error']}")
        return
    rows = (res.get("data") or {}).get("data", [])[:10]
    lines = []
    for i, r in enumerate(rows, 1):
        w = r.get("address", "?")
        pnl = r.get("total_pnl_usd", 0) or 0
        wr = r.get("win_rate", 0) or 0
        lines.append(f"{i}. `{w[:8]}…` ${pnl:,.0f} PnL, {wr:.0%} win")
    await status.edit_text(
        "Top smart-money wallets (7d, Solana):\n" + "\n".join(lines)
        + f"\n\n{'(cached, 0cr)' if res.get('cached') else '(live, 5cr)'} — /draft <wallet> to pick one",
        parse_mode="Markdown",
    )


async def draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None and update.effective_user is not None
    if not ctx.args:
        await update.message.reply_text("Usage: /draft <wallet>")
        return
    res = league.draft(update.effective_user.id, ctx.args[0])
    await update.message.reply_text(
        f"Drafted `{ctx.args[0][:12]}…` into round {res['round']} ({res['slots_left']} slots left)"
        if res["ok"] else res["error"],
        parse_mode="Markdown",
    )


async def picks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None and update.effective_user is not None
    ps = league.my_picks(update.effective_user.id)
    if not ps:
        await update.message.reply_text("No picks yet — /board then /draft <wallet>")
        return
    await update.message.reply_text(
        "Your picks:\n" + "\n".join(f"• `{p['wallet'][:12]}…`" for p in ps), parse_mode="Markdown"
    )


async def settle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    status = await update.message.reply_text("Settling on live PnL…")
    res = nansen_client.sm_leaderboard()
    if not res["ok"]:
        await status.edit_text(f"Blocked: {res['error']}")
        return
    pnls = {r.get("address"): (r.get("total_pnl_usd") or 0) for r in (res.get("data") or {}).get("data", [])}
    out = league.settle(pnls)
    if not out["scores"]:
        await status.edit_text("No drafted wallets matched the leaderboard this round.")
        return
    lines = sorted(out["scores"].items(), key=lambda kv: kv[1], reverse=True)
    await status.edit_text(
        f"Round {out['round']} settled:\n"
        + "\n".join(f"{u}: ${s:+,.0f}" for u, s in lines)
    )


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (talk to @BotFather for one)")
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(token).build()
    for cmd, fn in [("start", start), ("check", check), ("board", board),
                    ("draft", draft), ("picks", picks), ("settle", settle)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.run_polling()


if __name__ == "__main__":
    main()
