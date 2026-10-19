# Slice Shop — the OpenTelemetry Full Course lab

One small pizza shop, used in every chapter of the OpenTelemetry Full Course on the
Observability Labs YouTube channel.

```
loadgen ─▶ frontend (Node) ─▶ checkout (Python/FastAPI) ─┬─▶ payments (FastAPI) ── fastpay / legacy-gw
                                       │                 └─▶ kitchen (Flask)
                                       ├─▶ redis (prices)
                                       └─▶ postgres (orders)

every service ── OTLP ─▶ Collector ─┬─▶ Jaeger      (traces)
                                    ├─▶ Prometheus  (metrics, OTLP receiver)
                                    └─▶ Loki        (logs, OTLP endpoint) ─▶ Grafana
```

The app code has no OpenTelemetry in it. Python services run under `opentelemetry-instrument`,
and Node runs with `--require @opentelemetry/auto-instrumentations-node/register`: zero-code
instrumentation, configured only through `OTEL_*` environment variables in `docker-compose.yaml`.

## Run it

Needs Docker with Compose. Uses about 2 GB of RAM.

```sh
git clone https://github.com/karthikeyan-lgk/otel-full-course.git
cd otel-full-course
make up          # build + start; the load generator places ~2 orders/second
make order       # one order, Visa → fast gateway
make slow-order  # one order, Mastercard → legacy gateway
make down
```

| UI | URL |
| --- | --- |
| Shop | http://localhost:8080 |
| Jaeger (traces) | http://localhost:16686 |
| Grafana (metrics, logs, traces) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

## Run it on Kubernetes (chapter 9)

Needs [kind](https://kind.sigs.k8s.io/), kubectl and helm, and about 3 GB of RAM. Stop the compose lab first
(`make down`), because both use the same localhost ports.

```sh
make k8s-up      # two-node kind cluster, OpenTelemetry Operator, agent + gateway Collectors, Jaeger, Prometheus, the shop
make k8s-ui      # forwards the shop, Jaeger and Prometheus to localhost:8080 / 16686 / 9090
make k8s-down    # delete the cluster
```

The shop's start commands have no OpenTelemetry in them. One annotation per pod
(`instrumentation.opentelemetry.io/inject-python: "true"`) asks the Operator to inject the SDK, using the
`Instrumentation` in `k8s/instrumentation.yaml`. An agent Collector on every node adds Kubernetes metadata
(`k8sattributes`); a gateway Collector does the chapter 7 and 8 processing once.

## Trace an LLM call (chapter 11)

`GET /suggest?pizza=margherita` asks a model for one extra topping. Checkout calls it with the `openai` SDK,
and `opentelemetry-bootstrap` adds the GenAI instrumentation, so the call becomes a `chat` span with the model
and the token counts, plus `gen_ai.client.*` metrics. Any OpenAI-compatible endpoint works. Put the key in a
`.env` file next to `docker-compose.yaml` (it's git-ignored):

```sh
echo 'LLM_API_KEY=sk-or-...' > .env    # OpenRouter by default; also set LLM_BASE_URL / LLM_MODEL for others
make up
make suggest
```

Without a key `/suggest` answers 503 and everything else works as before. Nothing calls it on its own, so it
costs nothing until you do. Prompts and answers are not recorded unless you uncomment
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` in the compose file.

## Following the course

`main` is the lab as of the latest chapter. Each chapter that changes the code starts from a tag:

| Tag | State | Use it for |
| --- | --- | --- |
| `chapter-03` | zero-code instrumentation only, no OpenTelemetry in the app code | chapters 1–4 |
| `chapter-04` | plus the chapter 4 spans and attributes (checkout, payments) | chapter 5 |
| `chapter-05` | plus the chapter 5 metrics and exemplars (payments) | chapter 6 |
| `chapter-06` | plus the chapter 6 logging (pino frontend, quieter libraries) | chapter 7 |
| `chapter-07` | plus the chapter 7 Collector (filter, IP scrub, span metrics, self-monitoring) | chapter 8 |
| `chapter-08` | plus the chapter 8 tail sampling (head sampling lines commented in compose) | chapter 9 |
| `chapter-09` | plus the chapter 9 Kubernetes lab (`k8s/`, `make k8s-up`) | chapter 10 |
| `chapter-10` | plus the chapter 10 checklist (service.version, kitchen config file, buckets, redaction) | chapter 11 |

```sh
git checkout chapter-03   # then type the chapter 4 changes in yourself
git checkout chapter-04   # then add the chapter 5 metrics yourself
git checkout chapter-05   # then add the chapter 6 logging changes yourself
git checkout chapter-06   # then build the chapter 7 Collector config yourself
git checkout chapter-07   # then try head sampling and build the chapter 8 tail sampling yourself
git checkout chapter-08   # then add the chapter 9 k8s/ folder and make targets yourself
git checkout chapter-09   # then work through the chapter 10 checklist yourself
git checkout chapter-10   # then add the chapter 11 model call yourself
```

## The bug the course hunts

Cards starting with `5` go through the old `legacy-gw` gateway in payments. About a quarter of those
charges take 1.2–2 s, and 4% time out after 3 s (504). The logs never say "slow". You find it with the
latency histogram's p99, then the trace, then the gateway in the log line next to that trace.

## Versions (pinned)

Collector contrib 0.162.0 · Jaeger 2.22.0 · Prometheus 3.15.0 · Loki 3.6.18 · Grafana 13.2.4 ·
opentelemetry-distro 0.66b1 / exporter-otlp 1.45.1 · auto-instrumentations-node 0.81.1 ·
openai 3.35.1 / instrumentation-openai-v2 2.4b0 / util-genai 1.1b0 ·
Python 3.13 · Node 24 · Postgres 18.6 · Redis 8.10.2

## License

MIT, see [LICENSE](LICENSE). Use it, fork it, break it on purpose.
