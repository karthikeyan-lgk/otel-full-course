"""Prompt caching, measured: the shoe-store support bot from the token-bloat Short (same 1,031-word policy), on two
real cache-capable models through OpenRouter, every call traced with OpenTelemetry.

Models
  gpt   openai/gpt-5-nano via OpenAI      automatic prefix caching, no write fee
  qwen  qwen/qwen3.7-flash via Alibaba    explicit caching (cache_control); a cache write costs more than a plain read

Experiments (EXP=...)
  timestamp  20-turn chat, 5 runs per arm per model. Arm ts_first puts "Current time: <now>" at the top of the system
             prompt; ts_last puts it after the policy (and after qwen's cache breakpoint).
  breakeven  qwen only: k = 1, 2, 3, 5, 10 calls on one prefix, cache_control on vs off, 3 sequences each.
  expiry     both models: warm the cache, wait 10 s / 2 / 4 / 6 / 10 min, call again (2 reps each, run in parallel).

Every call: streamed (time to first content chunk), usage from OpenRouter (cached_tokens, cache_write_tokens, cost),
one span `chat <model>` with GenAI attributes, plus Prometheus counters/histogram. Rows go to out/calls.jsonl.
A budget guard stops everything at BUDGET_USD (default $1.00) of reported cost.
"""
import json, os, random, threading, time, urllib.error, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

HERE = Path(__file__).parent
for l in (HERE / ".env").read_text().splitlines() if (HERE / ".env").exists() else []:
    if l.startswith("OPENROUTER_API_KEY=") and "OPENROUTER_API_KEY" not in os.environ:
        os.environ["OPENROUTER_API_KEY"] = l.split("=", 1)[1].strip().strip('"')
POLICY = (HERE / "policy.txt").read_text()
MODELS = {"gpt": ("openai/gpt-5-nano", "OpenAI", False), "qwen": ("qwen/qwen3.7-flash", "Alibaba", True)}
QUESTIONS_ALL = ["Can I return worn running shoes?", "How long do refunds take?", "Do you ship to Canada?", "What if the box is damaged?",
             "Can I exchange for a different size?", "Is return shipping free?", "Do sale items count?", "How do I start a return?",
             "Can I return without a receipt?", "What about gift returns?", "Do you price match?", "Can I cancel an order?",
             "How long is the warranty?", "Do you resole shoes?", "What sizes do you stock?", "Can I pick up in store?",
             "Do you have kids' shoes?", "Is there a loyalty program?", "Can I change my address?", "Who do I call for help?"]
QUESTIONS = QUESTIONS_ALL[: int(os.environ.get("TURNS", "20"))]
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
BUDGET = float(os.environ.get("BUDGET_USD", "1.00"))
_lock = threading.Lock(); _spent = [0.0]

res = Resource.create({"service.name": "shoe-store-bot", "service.version": "2.0.0"})
tp = TracerProvider(resource=res); tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")))
trace.set_tracer_provider(tp); tracer = trace.get_tracer("prompt-caching-lab")
mp = MeterProvider(resource=res, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint="http://localhost:4318/v1/metrics"), export_interval_millis=3000)])
metrics.set_meter_provider(mp); meter = metrics.get_meter("prompt-caching-lab")
TOKENS = meter.create_counter("app.llm.input_tokens", unit="{token}", description="input tokens by kind: uncached, cache_read, cache_write")
COST = meter.create_counter("app.llm.cost", unit="USD", description="OpenRouter-reported cost")
TTFT = meter.create_histogram("app.llm.time_to_first_chunk", unit="s", explicit_bucket_boundaries_advisory=[0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5])


def system_message(key, nonce, ts_pos, cache_on):
    """System prompt = [time?] + policy (+ cache breakpoint for qwen) + [time?]."""
    now = "Current time: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = []
    if ts_pos == "first": parts.append({"type": "text", "text": now + "\n"})
    pol = {"type": "text", "text": f"Store policy {nonce}\n" + POLICY}
    if cache_on and MODELS[key][2]: pol["cache_control"] = {"type": "ephemeral"}
    parts.append(pol)
    if ts_pos == "last": parts.append({"type": "text", "text": "\n" + now})
    if ts_pos == "msg":  # the time in its own message after the policy message
        return [{"role": "system", "content": parts}, {"role": "system", "content": now}]
    return [{"role": "system", "content": parts}]


def call(key, messages, attrs):
    model, provider, _ = MODELS[key]
    with _lock:
        if _spent[0] >= BUDGET: raise SystemExit(f"budget ${BUDGET} reached")
    body = {"model": model, "provider": {"order": [provider], "allow_fallbacks": False}, "stream": True, "max_tokens": 60,
            "usage": {"include": True}, "messages": messages,
            **({"reasoning": {"effort": "minimal"}} if key == "gpt" else {"reasoning": {"enabled": False}, "temperature": 0})}
    with tracer.start_as_current_span(f"chat {model}", kind=trace.SpanKind.CLIENT) as s:
        s.set_attributes({"gen_ai.operation.name": "chat", "gen_ai.provider.name": "openrouter", "gen_ai.request.model": model,
                          "app.upstream_provider": provider, **attrs})
        for attempt in range(4):
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
                  {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"], "Content-Type": "application/json"})
            t0 = time.time(); ttft = None; usage = None; text = []
            try:
                for raw in urllib.request.urlopen(req, timeout=120):
                    line = raw.decode().strip()
                    if not line.startswith("data: ") or line == "data: [DONE]": continue
                    d = json.loads(line[6:])
                    delta = (d.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        if ttft is None: ttft = time.time() - t0
                        text.append(delta)
                    if d.get("usage"): usage = d["usage"]
                break
            except (urllib.error.URLError, TimeoutError) as e:
                s.add_event("retry", {"error": str(e)[:200]}); time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError("4 failed attempts")
        total = time.time() - t0
        u = usage or {}; det = u.get("prompt_tokens_details") or {}
        read, write, prompt = det.get("cached_tokens", 0) or 0, det.get("cache_write_tokens", 0) or 0, u.get("prompt_tokens", 0)
        cost = u.get("cost", 0.0) or 0.0
        s.set_attributes({"gen_ai.usage.input_tokens": prompt, "gen_ai.usage.output_tokens": u.get("completion_tokens", 0),
                          "gen_ai.usage.cache_read.input_tokens": read, "gen_ai.usage.cache_creation.input_tokens": write,
                          "app.cost_usd": cost, "app.time_to_first_chunk_s": round(ttft or -1, 3)})
    lab = {"model": key, "experiment": attrs.get("app.experiment"), "arm": attrs.get("app.arm")}
    TOKENS.add(read, {**lab, "kind": "cache_read"}); TOKENS.add(write, {**lab, "kind": "cache_write"})
    TOKENS.add(max(prompt - read - write, 0), {**lab, "kind": "uncached"}); COST.add(cost, lab)
    if ttft: TTFT.record(ttft, lab)
    row = {"t": round(time.time(), 2), **{k.replace("app.", ""): v for k, v in attrs.items()}, "model": key, "prompt_tokens": prompt,
           "cache_read": read, "cache_write": write, "output_tokens": u.get("completion_tokens", 0), "cost": cost,
           "ttft": round(ttft or -1, 3), "total_s": round(total, 3), "answer": "".join(text)[:120]}
    with _lock:
        _spent[0] += cost
        with open(OUT / "calls.jsonl", "a") as f: f.write(json.dumps(row) + "\n")
    return "".join(text) or "(no answer)", row


def conversation(key, arm, run):
    nonce = uuid.uuid4().hex[:10]; cid = f"{key}-{arm}-{run}-{nonce}"
    history = []
    with tracer.start_as_current_span("invoke_agent shoe-store-bot") as root:
        root.set_attributes({"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "shoe-store-bot",
                             "gen_ai.conversation.id": cid, "app.experiment": "timestamp", "app.arm": arm, "app.model_key": key})
        for turn, q in enumerate(QUESTIONS, 1):
            history.append({"role": "user", "content": q})
            if arm == "ts_end":  # the time as the very last message, after the whole history
                msgs = system_message(key, nonce, "none", True) + history[:-1] + [
                    {"role": "system", "content": "Current time: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}, history[-1]]
            elif arm == "no_cache":  # baseline: a new prefix every turn, no breakpoint, nothing reusable
                msgs = system_message(key, uuid.uuid4().hex[:10], "first", False) + history
            else:
                msgs = system_message(key, nonce, arm.split("_")[1], True) + history
            ans, _ = call(key, msgs, {"app.experiment": "timestamp", "app.arm": arm, "app.run": run, "app.turn": turn,
                                      "gen_ai.conversation.id": cid})
            history.append({"role": "assistant", "content": ans})


def exp_timestamp():
    for run in range(1, int(os.environ.get("RUNS", "5")) + 1):
        for key in MODELS:
            for arm in ("ts_first", "ts_last", "ts_msg"):
                conversation(key, arm, run); print("timestamp", key, arm, run, f"${_spent[0]:.4f}", flush=True)


def exp_breakeven():
    for seq in range(1, 4):
        for k in (1, 2, 3, 5, 10):
            for arm in os.environ.get("BE_ARMS", "cache_on,cache_off").split(","):
                nonce = uuid.uuid4().hex[:10]; cid = f"be-{arm}-{k}-{seq}-{nonce}"
                with tracer.start_as_current_span("invoke_agent shoe-store-bot") as root:
                    root.set_attributes({"gen_ai.conversation.id": cid, "app.experiment": "breakeven", "app.arm": arm, "app.k": k})
                    for i in range(1, k + 1):
                        q = random.Random(seq * 100 + i).choice(QUESTIONS)
                        n = uuid.uuid4().hex[:10] if arm == "no_cache" else nonce  # no_cache: a new prefix every call, nothing to reuse
                        call("qwen", system_message("qwen", n, "none", arm == "cache_on") + [{"role": "user", "content": q}],
                             {"app.experiment": "breakeven", "app.arm": arm, "app.k": k, "app.seq": seq, "app.call": i,
                              "gen_ai.conversation.id": cid})
                print("breakeven", arm, k, seq, f"${_spent[0]:.4f}", flush=True)


def exp_recheck():
    """Second look at qwen ts_last (1/95 in the main run) next to ts_msg, 3 fresh chats each."""
    for run in range(101, 104):
        for arm in ("ts_last", "ts_msg"):
            conversation("qwen", arm, run); print("recheck qwen", arm, run, f"${_spent[0]:.4f}", flush=True)


def exp_extra():
    """Review follow-ups: a true no-cache chat baseline and the time as the last message."""
    for run in range(201, 206):
        for key in MODELS:
            for arm in ("no_cache", "ts_end"):
                conversation(key, arm, run); print("extra", key, arm, run, f"${_spent[0]:.4f}", flush=True)


def exp_expiry():
    def one(key, gap, rep):
        nonce = uuid.uuid4().hex[:10]; cid = f"ex-{key}-{gap}-{rep}-{nonce}"
        q = [{"role": "user", "content": "How long do refunds take?"}]
        with tracer.start_as_current_span("invoke_agent shoe-store-bot") as root:
            root.set_attributes({"gen_ai.conversation.id": cid, "app.experiment": "expiry", "app.gap_s": gap})
            for i, wait in enumerate((0, gap), 1):
                time.sleep(wait)
                call(key, system_message(key, nonce, "none", True) + q,
                     {"app.experiment": "expiry", "app.arm": f"gap_{gap}s", "app.gap_s": gap, "app.rep": rep, "app.call": i,
                      "gen_ai.conversation.id": cid})
    ts = [threading.Thread(target=one, args=(k, g, r)) for k in MODELS for g in (10, 120, 240, 360, 600) for r in (1, 2)]
    for t in ts: t.start(); time.sleep(0.5)
    for t in ts: t.join()
    print("expiry done", f"${_spent[0]:.4f}", flush=True)


if __name__ == "__main__":
    for e in os.environ.get("EXP", "timestamp,breakeven,expiry").split(","):
        {"timestamp": exp_timestamp, "breakeven": exp_breakeven, "expiry": exp_expiry, "recheck": exp_recheck, "extra": exp_extra}[e]()
    tp.shutdown(); mp.shutdown()
    print(f"spent ${_spent[0]:.4f}")
