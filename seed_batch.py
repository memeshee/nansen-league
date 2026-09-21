#!/usr/bin/env python3
"""On-machine batch seeder: screener -> skip stables + already-graded ->
top 5 by volume -> full dossier -> save. Run on Fly via:
  fly ssh console -a smart-money-league --command "/app/seed_batch.py"
Burns ~10cr per dossier."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jev
import league
import nansen_client
from bot import trim, rows_of

STABLES = {"USDC", "USDT", "USDS", "PYUSD", "FDUSD", "USDe", "UXD", "PAI", "USD1"}


def screener():
    r = nansen_client.run(
        ["research", "token", "screener", "--chain", "solana", "--timeframe", "24h"],
        expected_credits=1,
        plan="dossier",
    )
    if not r.get("ok"):
        raise SystemExit(f"screener blocked: {r.get('error')}")
    return (r.get("data") or {}).get("data", [])


def dossier_one(mint: str):
    t0 = time.time()
    ev = nansen_client.fan(
        [
            ("flows", ["research", "token", "flows", "--token", mint, "--chain", "solana", "--days", "7"], 1, "dossier"),
            ("buyers", ["research", "token", "who-bought-sold", "--token", mint, "--chain", "solana", "--days", "7", "--buy-or-sell", "BUY"], 1, "dossier"),
            ("sellers", ["research", "token", "who-bought-sold", "--token", mint, "--chain", "solana", "--days", "7", "--buy-or-sell", "SELL"], 1, "dossier"),
            ("flowintel", ["research", "token", "flow-intelligence", "--token", mint, "--chain", "solana", "--timeframe", "7d"], 1, "dossier"),
            ("ohlcv", ["research", "token", "ohlcv", "--token", mint, "--chain", "solana", "--timeframe", "1d"], 1, "dossier"),
            ("holders", ["research", "token", "holders", "--token", mint, "--chain", "solana"], 5, "dossier"),
        ],
        plan="dossier",
    )
    if not any(v.get("ok") for v in ev.values()):
        print(f"{mint[:8]} BLOCKED", flush=True)
        return None
    state = {
        "token": mint, "chain": "solana",
        "flows_7d": trim(rows_of(ev["flows"])[-5:]),
        "top_buyers": trim(rows_of(ev["buyers"])[:8]),
        "top_sellers": trim(rows_of(ev["sellers"])[:8]),
        "flow_intelligence": trim(rows_of(ev["flowintel"])[:5]),
        "top_holders": trim(rows_of(ev["holders"])[:5]),
    }
    d = jev.dossier(state)
    candles = rows_of(ev["ohlcv"])
    entry = 0.0
    if candles:
        try:
            entry = float(candles[-1].get("close") or 0)
        except (TypeError, ValueError):
            pass
    did = league.save_dossier(mint, "solana", d["conviction"], d["action"], entry, json.dumps(trim(state)))
    print(f"#{did} {mint[:8]} conv={d['conviction']} action={d['action']} "
          f"conf={d['avg_conf']} entry={entry:.4f} secs={time.time()-t0:.0f}", flush=True)
    return did


def main():
    done = {d["mint"] for d in league.list_dossiers(limit=100)}
    cands = []
    for r in screener():
        if r.get("token_symbol") in STABLES:
            continue
        m = r.get("token_address", "")
        if not m or m in done:
            continue
        cands.append((r.get("volume") or 0, r.get("token_symbol", "?"), m))
    cands.sort(reverse=True)
    picks = cands[:5]
    print(f"candidates: {[(s, m[:6]) for _, s, m in picks]}", flush=True)
    for _, sym, mint in picks:
        try:
            dossier_one(mint)
        except Exception as e:
            print(f"{sym} FAILED: {e}", flush=True)


if __name__ == "__main__":
    main()
