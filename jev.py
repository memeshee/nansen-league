"""Jev (TypeSafe System One) judgments for the Nansen league bot.

One design rule: every user-facing verdict or spend decision goes through ONE
batched Jev request (independent questions in parallel), and code owns the
thresholds. Typed output guarantees the interface, not truth — validate scores
against known-good/bad tokens before trusting them live.
"""
import json
import os
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


def _api_key() -> str:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"].strip()
    with open(os.path.expanduser("~/.config/typesafe/api_key")) as f:
        return f.read().strip()


def judge(state: dict, questions: dict) -> dict:
    """Single batched request. Returns {answers, usage} or raises."""
    body = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    return {"answers": out["answers"], "usage": out.get("usage", {}), "model": out.get("model", "")}


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
