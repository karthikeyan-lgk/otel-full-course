# LLM prompt caching, measured with OpenTelemetry

The lab behind **Prompt Caching Explained: One Timestamp Killed My Cache** on the Observability Labs channel. Its own
small stack (Collector, Jaeger, Prometheus) on the usual ports, so run it on its own.

One shoe-store support bot with a 1,031-word return policy as its system prompt, answering 20 questions in a row, on
two real cache-capable models through OpenRouter:

- `openai/gpt-5-nano` (provider pinned to OpenAI): automatic prefix caching, no write fee. Reasoning `minimal`.
- `qwen/qwen3.7-flash` (provider pinned to Alibaba): a `cache_control` breakpoint on the policy block, and a cache
  write costs more than plain input. Reasoning off, temperature 0.

Every call is a span `chat <model>` with `gen_ai.usage.input_tokens`, `gen_ai.usage.cache_read.input_tokens`,
`gen_ai.usage.cache_creation.input_tokens`, `app.cost_usd` (OpenRouter-reported, output included) and the time to the
first streamed content chunk. Prometheus gets `app_llm_input_tokens_total{kind="uncached|cache_write|cache_read"}`,
`app_llm_cost_USD_total` and a time-to-first-chunk histogram.

## Run it

Needs Docker with Compose, Python 3.10+ and an OpenRouter key (the full run cost $0.084).

```sh
cd labs/llm-prompt-caching
echo 'OPENROUTER_API_KEY=sk-or-...' > .env        # git-ignored
docker compose -p otel-cache up -d              # Collector :4318, Jaeger :16686, Prometheus :9090
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
python lab.py                                   # timestamp, breakeven, expiry (~25 min, the expiry waits are real)
EXP=extra python lab.py                         # no-caching baseline + time as the last message
EXP=breakeven BE_ARMS=no_cache python lab.py    # fresh-prefix baseline for the break-even
EXP=recheck TURNS=10 python lab.py              # second look at qwen "time after the policy"
python analyze.py                               # out/summary.json
docker compose -p otel-cache down
```

`BUDGET_USD` (default 1.00) stops the run at that much reported cost. In Jaeger pick service `shoe-store-bot`, open a
trace and switch to GenAI View: each span shows Input, Output and Cached (read). In Prometheus:
`sum by (model, arm, kind) (app_llm_input_tokens_total{experiment="timestamp"})`.

## Results (2026-11-23, from [`results/`](results/))

Where the line `Current time: ...` sits in the prompt, 5 chats x 20 turns per setup. Hits = turns 2-20 that read
anything from the cache. Cost = OpenRouter-reported, per 1,000 chats.

| setup | gpt-5-nano hits | gpt $ / 1k chats | qwen hits | qwen $ / 1k chats |
| --- | --- | --- | --- | --- |
| no caching (new prefix every call) | 0/95 | 2.42 | 0/95 | 1.29 |
| time first | 0/95 | 2.41 | 0/95 | **1.51** |
| time after the policy, same system message | 75/95 | 1.56 | **1/95** | 1.48 |
| time in its own message after the policy | 78/95 | 1.52 | 95/95 | 0.55 |
| time as the last message | 76/95 | **1.24** | 95/95 | **0.51** |

- Time first on Qwen: it wrote the cache on every turn (148,500 write tokens) and read it 0 times, 17% more than no
  caching at all.
- Time after the policy, same message, on Qwen: 1/95, and 1/27 in a 3-chat recheck. Each write was about 26 tokens
  bigger than with the time in its own message (1,485-1,487 vs 1,458-1,462), roughly the size of the time line, so
  the stored block seems to include it. Not confirmed.
- Break-even (Qwen, one question per call on one policy, 3 sequences), cost vs a fresh prefix every call:
  breakpoint 1.22x / 0.72x / 0.54x / 0.40x / 0.30x for 1 / 2 / 3 / 5 / 10 calls; no breakpoint (Alibaba still cached
  some on its own) 0.98x / 0.69x / 0.58x / 0.50x / 0.47x.
- Expiry (warm, wait, ask again, 2 reps per wait): Qwen hit after 10 s, 2 and 4 min, missed after 6 and 10 min.
  gpt-5-nano hit 3 of 10 with no pattern by wait time.
- Time to first content chunk: median about 0.9 s on hits and misses alike (prompts 1.4-2.7k tokens).

Limits: two cheap models, one provider each, a ~1.5k-token policy just above the usual minimums, answers capped at 60
tokens, second-level timestamps, turns about 1 s apart, 5 chats per setup. Prices and cache rules differ by provider
and change; treat this as a demonstration of the mechanics, not a benchmark.
