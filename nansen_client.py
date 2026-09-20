"""Nansen CLI wrapper with credit-budget guard + short-TTL file cache.

Every paid call burns credits, so: Jev triages FIRST (see jev.py), then this
module enforces per-action and per-day caps and caches identical calls for
CACHE_TTL_S so the demo can't double-spend on re-renders.
"""
import hashlib
import json
import os
import subprocess
import time

NANSEN_BIN = "nansen"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nansen_cache")
CACHE_TTL_S = 600  # 10 min: leaderboard re-renders don't re-burn

# Real costs (free tier), from `nansen` cost map. Per-ACTION caps:
ACTION_BUDGET = {
    "glance": 1,   # Jev says noise -> max 1cr (flows / flow-intelligence / info)
    "deep": 6,     # Jev says conviction -> up to 5cr pnl + 1cr flows
    "settle": 5,   # weekly settlement leaderboard call
}
DAILY_CAP = 60  # hard stop per UTC day; demo budget ~500-800 total
SPEND_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spend_log.jsonl")


def _spent_today() -> int:
    today = time.strftime("%Y-%m-%d")
    total = 0
    if os.path.exists(SPEND_LOG):
        with open(SPEND_LOG) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("day") == today:
                        total += e.get("credits", 0)
                except ValueError:
                    pass
    return total


def _log_spend(cmd: str, credits: int):
    with open(SPEND_LOG, "a") as f:
        f.write(json.dumps({"day": time.strftime("%Y-%m-%d"), "ts": int(time.time()), "cmd": cmd, "credits": credits}) + "\n")


def _cache_key(args: list) -> str:
    return hashlib.sha256(" ".join(args).encode()).hexdigest()[:16]


def run(args: list, expected_credits: int, plan: str = "deep") -> dict:
    """Run `nansen <args>`. Enforces ACTION_BUDGET[plan] + DAILY_CAP + cache.

    Returns {"ok": True, "data": ..., "credits": N, "cached": bool} or
    {"ok": False, "error": ...} — never raises on budget, only on CLI failure.
    """
    if expected_credits > ACTION_BUDGET.get(plan, 1):
        return {"ok": False, "error": f"plan={plan} caps at {ACTION_BUDGET.get(plan, 1)}cr, call needs {expected_credits}cr"}
    if _spent_today() + expected_credits > DAILY_CAP:
        return {"ok": False, "error": f"daily cap {DAILY_CAP}cr hit ({_spent_today()}cr spent)"}

    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(args)
    cpath = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(cpath) and time.time() - os.path.getmtime(cpath) < CACHE_TTL_S:
        with open(cpath) as f:
            cached = json.load(f)
        cached["cached"] = True
        return cached

    env = dict(os.environ)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if "NANSEN_API_KEY" not in env and os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("NANSEN_API_KEY="):
                    env["NANSEN_API_KEY"] = line.strip().split("=", 1)[1]

    p = subprocess.run([NANSEN_BIN] + args, capture_output=True, text=True, timeout=120, env=env)
    if p.returncode != 0:
        return {"ok": False, "error": p.stderr.strip()[-500:] or p.stdout.strip()[-500:]}

    credits = expected_credits
    for line in p.stdout.splitlines():
        if line.startswith("Credits:"):
            try:
                credits = int(line.split()[1])
            except (IndexError, ValueError):
                pass
            break
    payload = p.stdout[p.stdout.find("{"):]
    try:
        data = json.loads(payload)
    except ValueError:
        return {"ok": False, "error": "CLI returned non-JSON"}

    _log_spend("nansen " + " ".join(args), credits)
    out = {"ok": True, "data": data.get("data", data), "credits": credits, "cached": False}
    with open(cpath, "w") as f:
        json.dump(out, f)
    return out


def sm_leaderboard(chain: str = "solana", days: int = 7, limit: int = 10) -> dict:
    return run(
        ["research", "smart-money-pnl-leaderboard", "--chains", chain, "--timeframe-days", str(days)],
        expected_credits=5,
        plan="settle" if days >= 7 else "deep",
    )


def token_flows(mint: str, chain: str = "solana", days: int = 7, plan: str = "glance") -> dict:
    return run(
        ["research", "token", "flows", "--token", mint, "--chain", chain, "--days", str(days)],
        expected_credits=1,
        plan=plan,
    )


def token_pnl(mint: str, chain: str = "solana", days: int = 7) -> dict:
    return run(
        ["research", "token", "pnl", "--token", mint, "--chain", chain, "--days", str(days)],
        expected_credits=5,
        plan="deep",
    )
