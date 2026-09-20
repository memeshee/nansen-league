"""Seed 5 real dossiers (STONK, CBBTC, ETH, PUMP, HYPE) for the track record."""
import json
import time

import jev
import league
import nansen_client
from bot import trim, rows_of

MINTS = [
    "6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx",   # STONK
    "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",   # CBBTC
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",   # ETH
    "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn",   # PUMP
    "98sMhvDwXj1RQi5c5Mndm3vPe9cBqPrbLaufMXFNMh5g",   # HYPE
]

for mint in MINTS:
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
    ok = {k: v.get("ok") for k, v in ev.items()}
    if not any(ok.values()):
        print(mint[:8], "BLOCKED", next(iter(ev.values())).get("error"), flush=True)
        continue
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
    print(f"#{did} {mint[:8]} conv={d['conviction']} action={d['action']} conf={d['avg_conf']} "
          f"entry={entry:.4f} fan={ok} secs={time.time()-t0:.0f}", flush=True)
