# AI agent span names and attributes, measured

The lab behind **AI Agent Observability: My Traces Hid 24 Wrong Answers (OpenTelemetry)** on the Observability Labs
channel. It's separate from the Slice Shop: its own small stack (Collector, Jaeger, Prometheus) on the same ports,
so run one or the other.

One support agent, one planted bug, traced two ways:

- **The bug:** the `get_refund_status` tool answers HTTP 200 with an empty list for premium users (as if their refunds
  sat in a table the query never reads). The agent tells them "I couldn't find any refund for this order." Nothing errors.
- **`MODE=generic`:** span names a team often starts with, `agent_call` / `llm_call` / `tool_call`, plus the HTTP
  client's auto-instrumented `POST` spans. No attributes of our own.
- **`MODE=designed`:** the OpenTelemetry GenAI span names (`invoke_agent support-agent`, `chat support-model-1`,
  `execute_tool <tool>`; model spans are `CLIENT` with `gen_ai.provider.name`) plus `gen_ai.conversation.id`,
  `app.user.tier`, `app.prompt.version`, `gen_ai.tool.name`, `app.tool.result_count` and token usage.
- The model and the tool API are small local stand-ins (deterministic, local HTTP), because the model isn't what's
  under test. The traces, the Collector, Jaeger and Prometheus are real.
- The Collector runs two `spanmetrics` connectors on the same spans: `lean` (dimensions: tool, tier) and `session`
  (tool, tier and the conversation ID).

## Run it

Needs Docker with Compose and Python 3.10+.

```sh
cd labs/ai-agent-span-names
docker compose -p otel-spans up -d          # Collector :4318, Jaeger :16686, Prometheus :9090
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http opentelemetry-instrumentation-urllib
MODE=generic python agent.py                # 1,000 chats, seed 7
MODE=designed python agent.py               # the same 1,000 chats
python query_jaeger.py                      # the questions a developer would ask, both modes
docker compose -p otel-spans down
```

Each run writes `out/<mode>_summary.json` and `out/<mode>_conversations.jsonl`. In Jaeger, pick service
`support-agent` and put `app.tool.result_count=0` in Attributes. In Prometheus, run
`count by (__name__) ({__name__=~"(lean|session).*"})`.

## Results (2026-11-23, 1,000 chats, seed 7)

From [`results/`](results/):

| | generic | designed |
| --- | --- | --- |
| wrong answers | 24, all premium | 24, all premium |
| spans with an error status | 0 of 6,172 | 0 of 6,172 |
| span names in Jaeger | 4 (`POST`, `agent_call`, `llm_call`, `tool_call`) | 5 (one per tool) |
| traces with a tool call | 793, all `tool_call` | 287 refund, 506 order |
| can a search find the 24? | no: no attribute holds the result | `app.tool.result_count=0` returns exactly 24 |
| trace bytes per chat (serialized, uncompressed OTLP) | 748 | 1,669 (2.2x) |

- Empty refund lookups by prompt version: refund-v4 18 of 158 (11%), refund-v3 6 of 129 (5%), so the prompt looks
  guilty. By tier: premium 24 of 24, pro 0 of 49, free 0 of 214. Tier explains all 24.
- Prometheus series from the same spans: `lean` 340, `session` 55,960 (165x). The conversation ID gives each chat its
  own series per operation, and every latency histogram multiplies that by its 17 buckets.
- `results/conversations.jsonl` is the ground truth: every chat, its tier, prompt version and answer.

The GenAI semantic conventions are still marked as in development, so names may change. One synthetic run: treat
it as a demonstration of the mechanics, not a benchmark.
