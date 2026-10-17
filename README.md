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

## Following the course

`main` is the lab as of the latest chapter. Each chapter that changes the code starts from a tag:

| Tag | State | Use it for |
| --- | --- | --- |
| `chapter-03` | zero-code instrumentation only, no OpenTelemetry in the app code | chapters 1–4 |
| `chapter-04` | plus the chapter 4 spans and attributes (checkout, payments) | chapter 5 |
| `chapter-05` | plus the chapter 5 metrics and exemplars (payments) | chapter 6 |

```sh
git checkout chapter-03   # then type the chapter 4 changes in yourself
git checkout chapter-04   # then add the chapter 5 metrics yourself
git checkout chapter-05   # then add the chapter 6 logging changes yourself
```

## The bug the course hunts

Cards starting with `5` go through the old `legacy-gw` gateway in payments. About a quarter of those
charges take 1.2–2 s, and 4% time out after 3 s (504). The logs never say "slow". You find it with the
latency histogram's p99, then the trace, then the gateway in the log line next to that trace.

## Versions (pinned)

Collector contrib 0.162.0 · Jaeger 2.22.0 · Prometheus 3.15.0 · Loki 3.6.18 · Grafana 13.2.4 ·
opentelemetry-distro 0.66b1 / exporter-otlp 1.45.1 · auto-instrumentations-node 0.81.1 ·
Python 3.13 · Node 24 · Postgres 18.6 · Redis 8.10.2

## License

MIT, see [LICENSE](LICENSE). Use it, fork it, break it on purpose.
