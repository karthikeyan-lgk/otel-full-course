"""One support agent, one planted bug, traced two ways.

MODE=generic   span names a team often starts with: agent_call / llm_call / tool_call, plus the HTTP client's
               auto-instrumented POST spans. No attributes of our own.
MODE=designed  OpenTelemetry GenAI span names (invoke_agent / chat / execute_tool) plus a few attributes:
               conversation id, user tier, prompt version, tool name, how many records the tool returned,
               token usage.

Both modes replay the same CONVERSATIONS conversations (same seed). The model is a small local stand-in
(deterministic, local HTTP) because the model is not what's under test; the tool API is local too.

The bug: get_refund_status returns HTTP 200 with an empty list for premium users (their refunds live in
another table). The agent then tells them "no refund found". Nothing errors.

Every span is also encoded as OTLP protobuf in-process, so the script can report the exact bytes each mode
would take as serialized, uncompressed OTLP protobuf (out/<mode>_summary.json): payload size, not network
traffic or backend spend."""
import json, os, random, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.instrumentation.urllib import URLLibInstrumentor

MODE = os.environ.get("MODE", "designed")
N = int(os.environ.get("CONVERSATIONS", "1000"))
SEED = int(os.environ.get("SEED", "7"))
MODEL = "support-model-1"
OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)


# ---------- local stand-ins: model API + tool API ----------
class Api(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        time.sleep(random.uniform(0.002, 0.008))
        if self.path == "/v1/chat/completions":
            msgs = body["messages"]; last = msgs[-1]
            p_tok = sum(len(m["content"]) for m in msgs) // 4 + 180
            if last["role"] == "user":  # plan: pick a tool from the intent
                intent = body["metadata"]["intent"]
                tool = {"refund": "get_refund_status", "order": "get_order_status"}.get(intent)
                out = {"tool": tool, "text": "" if tool else "Happy to help with that. Anything else?"}
            else:  # answer from the tool result
                res = json.loads(last["content"])
                if "refunds" in res:
                    out = {"tool": None, "text": f"Your refund of ${res['refunds'][0]['amount']} is {res['refunds'][0]['state']}."
                           if res["refunds"] else "I couldn't find any refund for this order."}
                else:
                    out = {"tool": None, "text": f"Your order is {res['status']}."}
            c_tok = len(out["text"]) // 4 + 6
            self._send({"choices": [{"message": out}], "usage": {"prompt_tokens": p_tok, "completion_tokens": c_tok}})
        elif self.path == "/tools/get_refund_status":
            # THE BUG: premium refunds are stored in a different table this query never reads.
            refunds = [] if body["tier"] == "premium" else [{"amount": 42, "state": "approved"}]
            self._send({"refunds": refunds})
        elif self.path == "/tools/get_order_status":
            self._send({"status": "out for delivery"})
        else:
            self.send_response(404); self.end_headers()

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Api)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def post(path, obj):
    req = urllib.request.Request(BASE + path, json.dumps(obj).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


# ---------- telemetry ----------
class ByteCounter(SpanExporter):
    """Counts the OTLP protobuf bytes the spans would take on the wire."""
    def __init__(self): self.bytes = 0; self.spans = 0; self.names = set(); self.attr_keys = set()
    def export(self, spans):
        self.bytes += len(encode_spans(spans).SerializeToString()); self.spans += len(spans)
        for s in spans: self.names.add(s.name); self.attr_keys.update(s.attributes.keys())
        return SpanExportResult.SUCCESS
    def shutdown(self): pass


service = "support-agent" if MODE == "designed" else "support-agent-generic"
tp = TracerProvider(resource=Resource.create({"service.name": service, "service.version": "1.4.0"}))
tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces"), max_queue_size=50000))
counter = ByteCounter()
tp.add_span_processor(BatchSpanProcessor(counter, max_queue_size=50000))
trace.set_tracer_provider(tp)
URLLibInstrumentor().instrument()
tracer = trace.get_tracer("support-agent")


# ---------- the agent ----------
def run(conv):
    cid, tier, intent, pv = conv["id"], conv["tier"], conv["intent"], conv["prompt_version"]
    common = {"gen_ai.conversation.id": cid, "app.user.tier": tier, "app.prompt.version": pv}
    designed = MODE == "designed"

    def model_call(messages):
        name = f"chat {MODEL}" if designed else "llm_call"
        kind = trace.SpanKind.CLIENT if designed else trace.SpanKind.INTERNAL
        with tracer.start_as_current_span(name, kind=kind) as s:
            r = post("/v1/chat/completions", {"model": MODEL, "messages": messages, "metadata": {"intent": intent}})
            if designed:
                s.set_attributes({**common, "gen_ai.operation.name": "chat", "gen_ai.provider.name": "local-standin",
                                  "gen_ai.request.model": MODEL,
                                  "gen_ai.usage.input_tokens": r["usage"]["prompt_tokens"],
                                  "gen_ai.usage.output_tokens": r["usage"]["completion_tokens"]})
            return r["choices"][0]["message"]

    root_name = "invoke_agent support-agent" if designed else "agent_call"
    with tracer.start_as_current_span(root_name) as root:
        if designed:
            root.set_attributes({**common, "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "support-agent"})
        msgs = [{"role": "system", "content": f"support prompt {pv}"}, {"role": "user", "content": conv["question"]}]
        plan = model_call(msgs)
        answer = plan["text"]
        if plan["tool"]:
            with tracer.start_as_current_span(f"execute_tool {plan['tool']}" if designed else "tool_call") as t:
                res = post(f"/tools/{plan['tool']}", {"order_id": conv["order_id"], "tier": tier})
                if designed:
                    count = len(res["refunds"]) if "refunds" in res else 1
                    t.set_attributes({**common, "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": plan["tool"],
                                      "app.tool.result_count": count})
            msgs.append({"role": "tool", "content": json.dumps(res)})
            answer = model_call(msgs)["text"]
        tid = format(root.get_span_context().trace_id, "032x")
    return answer, tid


rng = random.Random(SEED)
convs = []
for i in range(N):
    intent = rng.choices(["order", "refund", "other"], [50, 30, 20])[0]
    convs.append({"id": f"conv-{SEED}-{i:05d}", "tier": rng.choices(["free", "pro", "premium"], [70, 20, 10])[0],
                  "intent": intent, "prompt_version": rng.choice(["refund-v3", "refund-v4"]),
                  "order_id": f"A-{rng.randint(1000, 9999)}",
                  "question": {"order": "Where is my order?", "refund": "Did my refund go through?",
                               "other": "Can I change my delivery address?"}[intent]})

t0 = time.time()
rows = []
for c in convs:
    ans, tid = run(c)
    rows.append({**c, "answer": ans, "trace_id": tid, "wrong": ans.startswith("I couldn't find")})
tp.shutdown()
wrong = [r for r in rows if r["wrong"]]
summary = {"mode": MODE, "service": service, "conversations": N, "wrong_answers": len(wrong),
           "wrong_by_tier": {t: sum(r["tier"] == t for r in wrong) for t in ("free", "pro", "premium")},
           "refund_conversations": sum(r["intent"] == "refund" for r in rows),
           "spans": counter.spans, "otlp_bytes": counter.bytes, "bytes_per_conversation": round(counter.bytes / N),
           "span_names": sorted(counter.names), "attribute_keys": sorted(counter.attr_keys),
           "seconds": round(time.time() - t0, 1), "first_wrong_trace": wrong[0]["trace_id"] if wrong else None}
(OUT / f"{MODE}_conversations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
(OUT / f"{MODE}_summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps(summary, indent=1))
