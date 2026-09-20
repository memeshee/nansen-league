"""Fantasy Smart Money league state (SQLite).

MVP economy: each /draft costs the league the Nansen credits it burns;
entry is points-based (no real money). Weekly round settles on live
smart-money PnL leaderboard data — highest realized+unrealized total wins.
"""
import os
import sqlite3
import time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "league.db")
PICKS_PER_USER = 3
ROUND_SECONDS = 7 * 24 * 3600


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, points INTEGER DEFAULT 100)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS picks (user_id INTEGER, wallet TEXT, round_id INTEGER, entry_pnl REAL, "
        "PRIMARY KEY (user_id, wallet, round_id))"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS rounds (id INTEGER PRIMARY KEY, ends_at INTEGER, winner INTEGER)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dossiers (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, chain TEXT, "
        "ts INTEGER, conviction INTEGER, action TEXT, price REAL, detail TEXT)"
    )
    return conn


def current_round() -> int:
    conn = _db()
    row = conn.execute("SELECT id, ends_at FROM rounds ORDER BY id DESC LIMIT 1").fetchone()
    now = int(time.time())
    if row and row[1] > now:
        conn.close()
        return row[0]
    rid = (row[0] + 1) if row else 1
    conn.execute("INSERT INTO rounds (id, ends_at, winner) VALUES (?, ?, NULL)", (rid, now + ROUND_SECONDS))
    conn.commit()
    conn.close()
    return rid


def draft(user_id: int, wallet: str, entry_pnl: float = 0.0) -> dict:
    rid = current_round()
    conn = _db()
    conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
    n = conn.execute("SELECT COUNT(*) FROM picks WHERE user_id=? AND round_id=?", (user_id, rid)).fetchone()[0]
    if n >= PICKS_PER_USER:
        conn.close()
        return {"ok": False, "error": f"round {rid}: already holding {PICKS_PER_USER} picks"}
    conn.execute(
        "INSERT OR REPLACE INTO picks (user_id, wallet, round_id, entry_pnl) VALUES (?,?,?,?)",
        (user_id, wallet, rid, entry_pnl),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "round": rid, "pick": wallet, "slots_left": PICKS_PER_USER - n - 1}


def my_picks(user_id: int) -> list:
    rid = current_round()
    conn = _db()
    rows = conn.execute("SELECT wallet, entry_pnl FROM picks WHERE user_id=? AND round_id=?", (user_id, rid)).fetchall()
    conn.close()
    return [{"wallet": w, "entry_pnl": e} for w, e in rows]


def settle(wallet_pnls: dict) -> dict:
    """wallet_pnls: {wallet: current_total_pnl}. Scores = current - entry. Returns winners."""
    rid = current_round()
    conn = _db()
    rows = conn.execute("SELECT user_id, wallet, entry_pnl FROM picks WHERE round_id=?", (rid,)).fetchall()
    scores: dict = {}
    for uid, wallet, entry in rows:
        if wallet in wallet_pnls:
            scores[uid] = scores.get(uid, 0.0) + (wallet_pnls[wallet] - (entry or 0.0))
    if scores:
        winner = max(scores, key=lambda u: scores[u])
        conn.execute("UPDATE rounds SET winner=? WHERE id=?", (winner, rid))
        conn.execute("UPDATE users SET points = points + 50 WHERE id=?", (winner,))
        conn.commit()
    conn.close()
    return {"round": rid, "scores": scores}


def save_dossier(mint: str, chain: str, conviction: int, action: str, price: float, detail: str) -> int:
    conn = _db()
    cur = conn.execute(
        "INSERT INTO dossiers (mint, chain, ts, conviction, action, price, detail) VALUES (?,?,?,?,?,?,?)",
        (mint, chain, int(time.time()), conviction, action, price, detail),
    )
    conn.commit()
    did = cur.lastrowid or 0
    conn.close()
    return did


def list_dossiers(limit: int = 5) -> list:
    conn = _db()
    rows = conn.execute(
        "SELECT id, mint, chain, ts, conviction, action, price FROM dossiers ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [
        {"id": i, "mint": m, "chain": c, "ts": t, "conviction": v, "action": a, "price": p}
        for i, m, c, t, v, a, p in rows
    ]
