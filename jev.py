"""Jev (TypeSafe System One) judgments for the Nansen league bot.

One design rule: every user-facing verdict or spend decision goes through ONE
batched Jev request (independent questions in parallel), and code owns the
thresholds. Typed output guarantees the interface, not truth — validate scores
against known-good/bad tokens before trusting them live.
"""
import json
import os
import time
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


def _api_key() -> str:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"].strip()
    with open(os.path.expanduser("~/.config/typesafe/api_key")) as f:
        return f.read().strip()


def judge(state: dict, questions: dict, retries: int = 3) -> dict:
    """Single batched request. Returns {answers, usage} or raises.

    Retries transient network blips with backoff — host egress is flaky
    and a single SSL handshake timeout shouldn't fail a user command.
    """
    body = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode()
    last: Exception = RuntimeError("jev request failed")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                API_URL,
                data=body,
                headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                out = json.loads(resp.read().decode())
            return {"answers": out["answers"], "usage": out.get("usage", {}), "model": out.get("model", "")}
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


BULLISH_CRITERIA = [
    "Strongly bearish: smart money distributing, sellers dominate, holders concentrating in few wallets",
    "Neutral: mixed flows, no clear smart-money edge either way",
    "Strongly bullish: sustained smart-money accumulation, buyers dominate, healthy holder spread",
]

# Escalation ladder thresholds (tune on labeled data, not vibes)
DEEP_DIVE_YES = 0.65   # guard noul above -> spend up to 5cr deep analysis
DEEP_DIVE_NO = 0.35    # guard noul below -> 1cr glance only; between -> escalate
VERDICT_MIN_CONF = 0.50  # verdict confidence below -> flag for LLM teardown


def triage_token(ctx: dict) -> dict:
    """Batched Jev call: bullishness Score + spend-guard Noul over the same state.

    ctx keys: token, chain, smart_money_netflow_7d_usd, smart_money_buyers,
              smart_money_sellers, top10_holder_concentration, narrative
    Returns dict with score/confidence/guard_p/plan where plan is one of:
      glance   — cheap 1cr look only
      deep     — high-conviction, spend up to 5cr
      escalate — uncertain, needs full LLM teardown / human review
    """
    res = judge(
        ctx,
        {
            "bullishness": {
                "type": "score",
                "instructions": "How bullish is this token's smart-money flow?",
                "criteria": BULLISH_CRITERIA,
            },
            "worth_deep_dive": {
                "type": "noul",
                "instructions": "Is this token move worth spending 5 credits of deep Nansen analysis on, versus a 1-credit glance?",
            },
        },
    )
    bullish = res["answers"]["bullishness"]
    guard = res["answers"]["worth_deep_dive"]
    guard_p = guard["noul"]
    conf = bullish.get("confidence", 0.0)

    if guard_p >= DEEP_DIVE_YES and conf >= VERDICT_MIN_CONF:
        plan = "deep"
    elif guard_p <= DEEP_DIVE_NO and conf >= VERDICT_MIN_CONF:
        plan = "glance"
    else:
        plan = "escalate"

    verdict = "BULLISH" if bullish["score"] >= 1.33 else ("BEARISH" if bullish["score"] <= 0.67 else "NEUTRAL")
    return {
        "score": bullish["score"],
        "confidence": conf,
        "probabilities": bullish.get("probabilities", {}),
        "guard_p": guard_p,
        "verdict": verdict,
        "plan": plan,
        "usage": res["usage"],
    }


ACCUMULATION_CRITERIA = [
    "Weak hands: buyers are mostly unknown or unlabeled wallets, small size, no smart-money presence",
    "Mixed crowd: some labeled buyers but no dominant smart-money conviction",
    "Smart accumulation: labeled smart-money wallets buying size, repeat buyers, low seller overlap",
]

WHALE_RISK_CRITERIA = [
    "Diffuse: holders spread out, no single wallet can move the price",
    "Watchable: some concentration but active two-sided flow",
    "Fragile: top holders dominate supply and show distribution — one exit dumps the price",
]

ACTION_CRITERIA = {
    "accumulate": "Smart money is buying with size into a healthy structure — take exposure",
    "watch": "Mixed signals, thin data, or low confidence — wait for clarity, do not act yet",
    "avoid": "Distribution, whale concentration, or dump in progress — stay out",
}


def dossier(state: dict) -> dict:
    """One batched 5-question Jev request over assembled Nansen evidence.

    Returns per-dimension answers plus a code-composed conviction score
    (0-100). Code owns the weights and gates; Jev supplies the judgments.
    """
    res = judge(
        state,
        {
            "bullishness": {
                "type": "score",
                "instructions": "How bullish is this token's smart-money flow?",
                "criteria": BULLISH_CRITERIA,
            },
            "accumulation": {
                "type": "score",
                "instructions": "Who is buying this token — smart money with conviction, or an unknown crowd?",
                "criteria": ACCUMULATION_CRITERIA,
            },
            "whale_risk": {
                "type": "score",
                "instructions": "How fragile is this token's holder structure to a whale exit?",
                "criteria": WHALE_RISK_CRITERIA,
            },
            "dumping": {
                "type": "noul",
                "instructions": "Are top holders actively distributing (selling into strength) right now?",
            },
            "action": {
                "type": "choice",
                "instructions": "What should a trader do about this token right now?",
                "criteria": ACTION_CRITERIA,
            },
        },
    )
    a = res["answers"]
    bull = a["bullishness"]["score"] / 2 * 100
    acc = a["accumulation"]["score"] / 2 * 100
    safe = (2 - a["whale_risk"]["score"]) / 2 * 100
    dump_p = a["dumping"]["noul"]
    act = a["action"]["choice"]
    act_conf = a["action"].get("confidence", 0.0)
    conviction = round(0.4 * bull + 0.3 * acc + 0.2 * safe + 0.1 * act_conf * 100)
    if act == "avoid" or dump_p > 0.7:
        conviction = min(conviction, 25)
    if act == "watch":
        conviction = min(conviction, 55)
    confs = [
        a["bullishness"].get("confidence", 0.0),
        a["accumulation"].get("confidence", 0.0),
        a["whale_risk"].get("confidence", 0.0),
        act_conf,
    ]
    avg_conf = sum(confs) / len(confs)
    return {
        "bull": round(bull),
        "acc": round(acc),
        "safe": round(safe),
        "dump_p": round(dump_p, 2),
        "action": act,
        "act_conf": round(act_conf, 2),
        "conviction": conviction,
        "avg_conf": round(avg_conf, 2),
        "escalate": avg_conf < VERDICT_MIN_CONF,
        "usage": res["usage"],
    }


CONSISTENCY_CRITERIA = [
    "One-hit wonder: a single lucky trade dominates, the rest is noise",
    "Streaky: some repeat wins but high variance across tokens",
    "Consistent: repeat realized profits across multiple tokens and weeks",
]

DEGEN_CRITERIA = [
    "Disciplined: sized bets, takes profit, diverse book",
    "Punty: some oversized bets but survives them",
    "Degen: all-in gambles, round-trips winners, blows up often",
]


def scout_wallet(state: dict) -> dict:
    """Two-question Jev batch over profiler evidence. Grade composed in code."""
    res = judge(
        state,
        {
            "consistency": {
                "type": "score",
                "instructions": "How consistent is this wallet's trading edge?",
                "criteria": CONSISTENCY_CRITERIA,
            },
            "degen": {
                "type": "score",
                "instructions": "How reckless is this wallet's risk behavior?",
                "criteria": DEGEN_CRITERIA,
            },
        },
    )
    a = res["answers"]
    con, dg = a["consistency"]["score"], a["degen"]["score"]
    if con >= 1.33 and dg <= 0.67:
        grade = "S"
    elif con >= 1.0 and dg <= 1.0:
        grade = "A"
    elif con >= 0.67 or dg <= 1.33:
        grade = "B"
    else:
        grade = "C"
    return {
        "consistency": round(con, 2),
        "degen": round(dg, 2),
        "grade": grade,
        "conf": round((a["consistency"].get("confidence", 0) + a["degen"].get("confidence", 0)) / 2, 2),
        "usage": res["usage"],
    }


if __name__ == "__main__":
    demo = triage_token(
        {
            "token": "JUP",
            "chain": "solana",
            "smart_money_netflow_7d_usd": 12500000,
            "smart_money_buyers": 342,
            "smart_money_sellers": 118,
            "top10_holder_concentration": 0.31,
            "narrative": "Jupiter perp volume strong, funding positive",
        }
    )
    print(json.dumps(demo, indent=2))
