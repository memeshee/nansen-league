"""Fantasy Smart Money league + due-diligence copilot Telegram bot.

Flagship: /deep dossier — parallel Nansen fan-out (6 endpoints, 10cr) into
ONE batched 5-question Jev request, composed into a 0-100 conviction score
in code. /record grades past dossiers against later price (the validation
loop). /draft scouts wallets via profiler + Jev. /budget shows the economy.

Robustness notes (learned live): host egress to api.telegram.org is flaky
(TimedOut/ReadError), so every handler reports failures back to the user
instead of leaving "…" status messages hanging, and HTTP timeouts are raised.
"""
import json
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest

import jev
import league
import nansen_client

log = logging.getLogger(__name__)


def trim(obj, max_list=8, max_str=120, depth=0):
    """Shrink Nansen payloads for Jev state: keep scalars, cap lists/strings."""
    if depth > 2:
        return "…"
    if isinstance(obj, dict):
        return {k: trim(v, max_list, max_str, depth + 1) for k, v in list(obj.items())[:20]}
    if isinstance(obj, (list, tuple)):
        return [trim(v, max_list, max_str, depth + 1) for v in obj[:max_list]]
    if isinstance(obj, str):
        return obj[:max_str]
    return obj


def bar(v: int) -> str:
    n = max(0, min(10, round(v / 10)))
    return "█" * n + "░" * (10 - n)


def rows_of(res: dict) -> list:
    return (res.get("data") or {}).get("data", []) if res.get("ok") else []


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.exception("handler failed: %s", ctx.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                f"Bot error: {ctx.error}. Connection has been flaky — just retry."
            )
        except Exception:
            pass


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    await update.message.reply_text(
        "Fantasy Smart Money League.\n"
        "/check <mint> — instant Jev verdict (1-6cr)\n"
        "/deep <mint> — full dossier: 6 Nansen endpoints + 5 Jev judgments, 0-100 conviction (10cr)\n"
        "/record — track record: past dossiers graded vs later price\n"
        "/board — top smart-money wallets (5cr, cached 10m)\n"
        "/draft <wallet> — draft + Jev scout report (2cr)\n"
        "/picks — your picks\n"
        "/settle — settle the round on live PnL\n"
        "/budget — today's credit spend"
    )


async def check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    if not ctx.args:
        await update.message.reply_text("Usage: /check <mint> [chain=solana]")
        return
    mint, chain = ctx.args[0], (ctx.args[1] if len(ctx.args) > 1 else "solana")
    status = await update.message.reply_text("Jev triaging…")

    try:
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
    except Exception as e:  # never leave "triaging…" hanging
        log.exception("check %s failed", mint)
        try:
            await status.edit_text(f"/check failed: {e}. Nothing burned beyond cache — retry.")
        except Exception:
            pass


async def deep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Flagship: 6-endpoint parallel fan-out + 5-question Jev batch + conviction."""
    assert update.message is not None
    if not ctx.args:
        await update.message.reply_text("Usage: /deep <mint> [chain=solana]")
        return
    mint, chain = ctx.args[0], (ctx.args[1] if len(ctx.args) > 1 else "solana")
    status = await update.message.reply_text("Fanning out across 6 Nansen endpoints…")

    try:
        ev = nansen_client.fan(
            [
                ("flows", ["research", "token", "flows", "--token", mint, "--chain", chain, "--days", "7"], 1, "dossier"),
                ("buyers", ["research", "token", "who-bought-sold", "--token", mint, "--chain", chain, "--days", "7", "--buy-or-sell", "BUY"], 1, "dossier"),
                ("sellers", ["research", "token", "who-bought-sold", "--token", mint, "--chain", chain, "--days", "7", "--buy-or-sell", "SELL"], 1, "dossier"),
                ("flowintel", ["research", "token", "flow-intelligence", "--token", mint, "--chain", chain, "--timeframe", "7d"], 1, "dossier"),
                ("ohlcv", ["research", "token", "ohlcv", "--token", mint, "--chain", chain, "--timeframe", "1d"], 1, "dossier"),
                ("holders", ["research", "token", "holders", "--token", mint, "--chain", chain], 5, "dossier"),
            ],
            plan="dossier",
        )
        if all(not (v.get("ok")) for v in ev.values()):
            await status.edit_text(f"Dossier blocked: {next(iter(ev.values())).get('error', 'all calls failed')}")
            return

        await status.edit_text("Evidence in — Jev judging 5 dimensions…")
        state = {
            "token": mint,
            "chain": chain,
            "flows_7d": trim(rows_of(ev["flows"])[-5:]),
            "top_buyers": trim(rows_of(ev["buyers"])[:8]),
            "top_sellers": trim(rows_of(ev["sellers"])[:8]),
            "flow_intelligence": trim(rows_of(ev["flowintel"])[:5]),
            "top_holders": trim(rows_of(ev["holders"])[:5]),
        }
        d = jev.dossier(state)
        spent = sum(v.get("credits", 0) for v in ev.values() if v.get("ok") and not v.get("cached"))

        candles = rows_of(ev["ohlcv"])
        entry = 0.0
        if candles:
            try:
                entry = float(candles[-1].get("close") or 0)
            except (TypeError, ValueError):
                pass
        did = league.save_dossier(mint, chain, d["conviction"], d["action"], entry, json.dumps(trim(state)))

        esc = "\nESCALATE to LLM teardown (low confidence)." if d["escalate"] else ""
        await status.edit_text(
            f"Dossier #{did} `{mint}` — conviction {d['conviction']}/100 → {d['action'].upper()}\n"
            f"Bullish flow {bar(d['bull'])} {d['bull']}\n"
            f"Accumulation {bar(d['acc'])} {d['acc']}\n"
            f"Holder safety {bar(d['safe'])} {d['safe']}\n"
            f"Dump risk {d['dump_p']:.2f} · action conf {d['act_conf']:.2f} · avg conf {d['avg_conf']:.2f}\n"
            f"Evidence: 10cr spent ({'cached' if spent == 0 else 'live'}) · entry ${entry:,.2f}{esc}\n"
            f"Graded later via /record.",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("deep %s failed", mint)
        try:
            await status.edit_text(f"/deep failed: {e}. Retry.")
        except Exception:
            pass


async def record(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Grade past dossiers vs subsequent price. The validation loop."""
    assert update.message is not None
    ds = league.list_dossiers(limit=4)
    if not ds:
        await update.message.reply_text("No dossiers yet — run /deep <mint> first.")
        return
    status = await update.message.reply_text(f"Grading {len(ds)} dossiers vs live price…")
    try:
        lines, hits, graded = [], 0, 0
        for x in ds:
            q = nansen_client.token_ohlcv(x["mint"], x["chain"], plan="record")
            candles = rows_of(q)
            if not candles or not x["price"]:
                lines.append(f"#{x['id']} `{x['mint'][:8]}…` {x['action']} @{x['conviction']}: no price data")
                continue
            try:
                now = float(candles[-1].get("close") or 0)
            except (TypeError, ValueError):
                continue
            ret = (now - x["price"]) / x["price"] * 100 if x["price"] else 0
            if x["action"] == "watch":
                mark = "➖" if abs(ret) < 10 else ("✗" if (ret > 0) != (x["conviction"] > 30) else "➖")
                if mark == "➖":
                    hits += 1
            else:
                good = (ret > 0) == (x["action"] == "accumulate")
                mark = "✓" if good else "✗"
                hits += 1 if good else 0
            graded += 1
            lines.append(f"{mark} #{x['id']} `{x['mint'][:8]}…` {x['action']} @{x['conviction']}: {ret:+.1f}% since")
        rate = f"{hits}/{graded} = {hits / graded:.0%}" if graded else "n/a"
        await status.edit_text(f"Track record ({rate} calls correct):\n" + "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        log.exception("record failed")
        try:
            await status.edit_text(f"/record failed: {e}. Retry.")
        except Exception:
            pass


async def budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    spent = nansen_client.spend_today()
    bd = nansen_client.spend_breakdown()
    n_dos = len(league.list_dossiers(limit=100))
    lines = [f"• {cmd}: {cr}cr ({n} calls)" for cmd, cr, n in sorted(bd, key=lambda t: -t[1])[:10]]
    await update.message.reply_text(
        f"Today: {spent}/{nansen_client.DAILY_CAP}cr burned · {n_dos} dossiers stored\n"
        + ("\n".join(lines) if lines else "No spend yet today.")
    )


async def board(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    status = await update.message.reply_text("Pulling smart-money leaderboard (5cr)…")
    try:
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
            lines.append(f"{i}. ${pnl:,.0f} PnL · {wr:.0%} win\n`{w}`")
        await status.edit_text(
            "Top smart-money wallets (7d, Solana):\n" + "\n".join(lines)
            + f"\n\n{'(cached, 0cr)' if res.get('cached') else '(live, 5cr)'} — /draft <wallet> to pick one",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("board failed")
        try:
            await status.edit_text(f"/board failed: {e}. Retry.")
        except Exception:
            pass


async def draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None and update.effective_user is not None
    if not ctx.args:
        await update.message.reply_text("Usage: /draft <wallet>")
        return
    try:
        wallet = ctx.args[0]
        res = league.draft(update.effective_user.id, wallet)
        if not res["ok"]:
            await update.message.reply_text(res["error"])
            return
        await update.message.reply_text(
            f"Drafted `{wallet[:12]}…` into round {res['round']} "
            f"({res['slots_left']} of your {league.PICKS_PER_USER} picks left). Scouting…",
            parse_mode="Markdown",
        )
        # Scout report: profiler bundle (2cr) + Jev grade. Draft stands regardless.
        try:
            ev = nansen_client.fan(
                [
                    ("pnl", ["research", "profiler", "pnl-summary", "--address", wallet, "--chain", "solana", "--days", "30"], 1, "scout"),
                    ("bal", ["research", "profiler", "balance", "--address", wallet, "--chain", "solana"], 1, "scout"),
                ],
                plan="scout",
            )
            if ev["pnl"].get("ok") or ev["bal"].get("ok"):
                s = jev.scout_wallet(
                    {
                        "wallet": wallet,
                        "pnl_summary": trim(rows_of(ev["pnl"])[:1] or (ev["pnl"].get("data") or {})),
                        "balances": trim(rows_of(ev["bal"])[:10]),
                    }
                )
                await update.message.reply_text(
                    f"Scout: grade {s['grade']} (consistency {s['consistency']}, degen risk {s['degen']}, conf {s['conf']})",
                )
            else:
                await update.message.reply_text("Scout unavailable (credit guard) — pick stands.")
        except Exception:
            log.exception("scout failed")
            await update.message.reply_text("Scout failed — pick stands, retry /picks later.")
    except Exception as e:
        log.exception("draft failed")
        await update.message.reply_text(f"/draft failed: {e}. Retry.")


async def picks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None and update.effective_user is not None
    ps = league.my_picks(update.effective_user.id)
    if not ps:
        await update.message.reply_text("No picks yet — /board then /draft <wallet>")
        return
    await update.message.reply_text(
        f"Your picks ({len(ps)}/{league.PICKS_PER_USER} this round):\n" + "\n".join(f"• `{p['wallet'][:12]}…`" for p in ps), parse_mode="Markdown"
    )


async def settle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    status = await update.message.reply_text("Settling on live PnL…")
    try:
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
    except Exception as e:
        log.exception("settle failed")
        try:
            await status.edit_text(f"/settle failed: {e}. Retry.")
        except Exception:
            pass


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (talk to @BotFather for one)")
    logging.basicConfig(level=logging.INFO)
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=20.0)
    app = Application.builder().token(token).request(request).build()
    for cmd, fn in [("start", start), ("check", check), ("deep", deep), ("record", record),
                    ("board", board), ("draft", draft), ("picks", picks),
                    ("settle", settle), ("budget", budget)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_error_handler(on_error)
    app.run_polling()


if __name__ == "__main__":
    main()
