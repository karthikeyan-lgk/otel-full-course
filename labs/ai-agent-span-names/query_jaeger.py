"""Ask Jaeger the questions a developer would ask, in both modes (Jaeger v2 API v3)."""
import json, sys, time, urllib.request, urllib.parse
from collections import Counter
J = "http://localhost:16686/api/v3"
def get(path, **q):
    return json.load(urllib.request.urlopen(J + path + "?" + urllib.parse.urlencode(q)))
def spans(svc, op=None, attrs=None):
    now = time.time()
    q = {"query.service_name": svc, "query.start_time_min": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 7200)),
         "query.start_time_max": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 60)), "query.search_depth": 5000}
    if op: q["query.operation_name"] = op
    if attrs: q["query.attributes"] = json.dumps(attrs)
    try: r = get("/traces", **q)
    except urllib.error.HTTPError as e:
        if e.code == 404: return {}
        raise
    out = {}
    for rs in r["result"]["resourceSpans"]:
        for ss in rs["scopeSpans"]:
            for s in ss["spans"]:
                out.setdefault(s["traceId"], []).append(s)
    return out
def attr(s, k):
    for a in s.get("attributes", []):
        if a["key"] == k: return list(a["value"].values())[0]
res = {}
for svc in ("support-agent-generic", "support-agent"):
    res[svc] = {"operations": sorted(o["name"] for o in get("/operations", service=svc)["operations"]),
                "traces": len(all_ := spans(svc)),
                "span_status_codes": dict(Counter((s.get("status") or {}).get("code", "UNSET") for t in all_.values() for s in t))}
g = "support-agent-generic"
res[g]["tool_call_traces"] = len(spans(g, op="tool_call"))
d = "support-agent"
refund = spans(d, op="execute_tool get_refund_status")
empty = spans(d, op="execute_tool get_refund_status", attrs={"app.tool.result_count": "0"})
res[d]["refund_tool_traces"] = len(refund)
res[d]["refund_tool_result_count_0"] = len(empty)
res[d]["result_count_0_any_operation"] = len(spans(d, attrs={"app.tool.result_count": "0"}))
for k in ("app.user.tier", "app.prompt.version"):
    c = Counter(attr(s, k) for t in empty.values() for s in t if s["name"].startswith("execute_tool"))
    res[d][f"empty_by_{k}"] = dict(c)
    res[d][f"refund_calls_by_{k}"] = dict(Counter(attr(s, k) for t in refund.values() for s in t if s["name"].startswith("execute_tool")))
json.dump(res, open("out/jaeger_queries.json", "w"), indent=1); print(json.dumps(res, indent=1))
