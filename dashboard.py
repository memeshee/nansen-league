"""Realtime dashboard + landing page for the Nansen league bot (stdlib only).

JSON APIs read league.db and nansen_client's 10-min file cache, so page
polling burns 0 extra credits. Acting happens in Telegram: every wallet and
mint ships a tap-to-copy command plus a t.me deep link into the bot.
"""
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import league
import nansen_client

PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "righttofight_bot")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"}


def rows_of(res: dict) -> list:
    return (res.get("data") or {}).get("data", []) if res.get("ok") else []


def api_record():
    out, hits, graded = [], 0, 0
    for x in league.list_dossiers(limit=4):
        q = nansen_client.token_ohlcv(x["mint"], x["chain"], plan="record")
        candles = rows_of(q)
        if not candles or not x["price"]:
            out.append({**x, "ret": None})
            continue
        try:
            now = float(candles[-1].get("close") or 0)
        except (TypeError, ValueError):
            out.append({**x, "ret": None})
            continue
        ret = round((now - x["price"]) / x["price"] * 100, 1) if x["price"] else 0
        if x["action"] == "watch":
            good = abs(ret) < 10
        else:
            good = (ret > 0) == (x["action"] == "accumulate")
        hits += 1 if good else 0
        graded += 1
        out.append({**x, "ret": ret, "now": now, "good": good})
    return {"dossiers": out, "hits": hits, "graded": graded}


def api_board():
    res = nansen_client.sm_leaderboard()
    rows = []
    for r in rows_of(res)[:10]:
        rows.append({
            "address": r.get("address", "?"),
            "pnl": r.get("total_pnl_usd") or 0,
            "win_rate": r.get("win_rate") or 0,
            "trades": r.get("n_trades") or 0,
        })
    return {"rows": rows, "cached": bool(res.get("cached")), "bot": BOT_USERNAME}


def api_budget():
    return {
        "spent": nansen_client.spend_today(),
        "cap": nansen_client.DAILY_CAP,
        "breakdown": [{"cmd": k, "credits": c, "calls": n} for k, c, n in nansen_client.spend_breakdown()],
        "dossiers": len(league.list_dossiers(limit=1000)),
    }


ROUTES = {
    "/api/dossiers": lambda: {"dossiers": league.list_dossiers(limit=10), "bot": BOT_USERNAME},
    "/api/board": api_board,
    "/api/record": api_record,
    "/api/budget": api_budget,
    "/api/round": lambda: {**league.round_info(), "bot": BOT_USERNAME},
}


class Handler(BaseHTTPRequestHandler):
    server_version = "LeagueDesk/1.0"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ROUTES:
            try:
                self._send(json.dumps(ROUTES[path]()).encode(), "application/json")
            except Exception as e:  # API never 500s the page
                self._send(json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if path == "/":
            path = "/index.html"
        fpath = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not fpath.startswith(STATIC) or not os.path.isfile(fpath):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(fpath)[1]
        with open(fpath, "rb") as f:
            self._send(f.read(), MIME.get(ext, "application/octet-stream"))


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"LeagueDesk on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
