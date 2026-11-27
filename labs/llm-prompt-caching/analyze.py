"""Summarise out/calls.jsonl into out/summary.json (and print it).

Timestamp arms: runs 1-5 (ts_first / ts_last / ts_msg) and 201-205 (no_cache / ts_end), 20 turns each.
Recheck: runs 101-103, qwen ts_last vs ts_msg, 10 turns each. Hits = turns 2+ with cache_read > 0.
"""
import json, statistics as st
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).parent / "out"
SRC = OUT if (OUT / "calls.jsonl").exists() else Path(__file__).parent / "results"  # no run of your own yet: use ours
rows = [json.loads(l) for l in open(SRC / "calls.jsonl")]
OUT.mkdir(exist_ok=True)
S = {"calls": len(rows), "spent_usd": round(sum(r["cost"] for r in rows), 5)}
med = lambda xs: round(st.median(xs), 3) if xs else None
cid = lambda r: r.get("gen_ai.conversation.id") or r.get("conversation.id")


def arms(rs):
    g = defaultdict(list)
    for r in rs: g[(r["model"], r["arm"])].append(r)
    T = {}
    for (m, a), xs in sorted(g.items()):
        convs = defaultdict(list)
        for r in xs: convs[cid(r)].append(r)
        later = [r for r in xs if r["turn"] >= 2]
        T[f"{m}/{a}"] = {
            "chats": len(convs), "calls": len(xs),
            "hits_turn2plus": f"{sum(r['cache_read'] > 0 for r in later)}/{len(later)}",
            "cache_read_share_of_input": round(sum(r["cache_read"] for r in xs) / sum(r["prompt_tokens"] for r in xs), 3),
            "cache_read_tokens": sum(r["cache_read"] for r in xs), "cache_write_tokens": sum(r["cache_write"] for r in xs),
            "cost_per_chat_usd": round(st.mean(sum(x["cost"] for x in c) for c in convs.values()), 6),
            "ttft_median_hit_s": med([r["ttft"] for r in later if r["cache_read"] > 0 and r["ttft"] > 0]),
            "ttft_median_miss_s": med([r["ttft"] for r in later if r["cache_read"] == 0 and r["ttft"] > 0]),
        }
    return T


ts = [r for r in rows if r["experiment"] == "timestamp"]
S["timestamp"] = arms([r for r in ts if not 100 < r["run"] < 200])
S["recheck_10_turns"] = arms([r for r in ts if 100 < r["run"] < 200])

be = [r for r in rows if r["experiment"] == "breakeven"]
seqs = defaultdict(list)
for r in be: seqs[(r["arm"], r["k"], r["seq"])].append(r)
mean_cost = lambda arm, k: st.mean(sum(x["cost"] for x in v) for (a, kk, _), v in seqs.items() if a == arm and kk == k)
S["breakeven_qwen"] = {str(k): {"breakpoint_usd": round(mean_cost("cache_on", k), 7), "no_breakpoint_usd": round(mean_cost("cache_off", k), 7),
                                "fresh_prefix_usd": round(mean_cost("no_cache", k), 7),
                                "breakpoint_vs_fresh": round(mean_cost("cache_on", k) / mean_cost("no_cache", k), 2),
                                "no_breakpoint_vs_fresh": round(mean_cost("cache_off", k) / mean_cost("no_cache", k), 2)}
                       for k in sorted({r["k"] for r in be})}

ex = [r for r in rows if r["experiment"] == "expiry" and r.get("call") == 2]
E = defaultdict(dict)
for r in sorted(ex, key=lambda r: (r["model"], r["gap_s"], r["rep"])):
    E[r["model"]].setdefault(str(r["gap_s"]), []).append({"cache_read": r["cache_read"], "cache_write": r["cache_write"], "cost": r["cost"]})
S["expiry_second_call"] = E

(OUT / "summary.json").write_text(json.dumps(S, indent=1))
print(json.dumps(S, indent=1))
