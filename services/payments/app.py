"""Payments: charges the card through one of two gateways.

The bug the course hunts: cards starting with 5 go through the old "legacy-gw" gateway,
which is sometimes very slow and occasionally times out. Nothing in the logs says
"slow" — you find it in the traces.
"""

import logging
import random
import time

from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace
from pydantic import BaseModel

log = logging.getLogger("payments")
tracer = trace.get_tracer("slice-shop.payments")
meter = metrics.get_meter("slice-shop.payments")
logging.basicConfig(level=logging.INFO)

# Chapter 5: two numbers the shop actually cares about, by gateway.
charges = meter.create_counter(
    "payments.charges", unit="{charge}", description="Card charges, by gateway and outcome"
)
gateway_duration = meter.create_histogram(
    "payments.gateway.duration",
    unit="s",
    description="How long the card gateway took to answer",
    explicit_bucket_boundaries_advisory=[0.05, 0.1, 0.25, 0.5, 1, 1.5, 2, 3, 5],
)

app = FastAPI()


class Charge(BaseModel):
    order_id: str
    amount: int
    card: str


def gateway_for(card: str) -> str:
    return "legacy-gw" if card.startswith("5") else "fastpay"


def brand_of(card: str) -> str:
    return "mastercard" if card.startswith("5") else "visa"


def call_gateway(gateway: str) -> None:
    """Stand-in for the real card network call."""
    if gateway == "legacy-gw":
        roll = random.random()
        if roll < 0.04:
            time.sleep(3.0)
            raise TimeoutError(f"{gateway} did not answer")
        time.sleep(random.uniform(1.2, 2.0) if roll < 0.30 else random.uniform(0.04, 0.09))
    else:
        time.sleep(random.uniform(0.03, 0.08))


def record_charge(gateway: str, outcome: str, started: float) -> None:
    # Recorded inside the span, so the SDK can attach this trace as an exemplar.
    attrs = {"payment.gateway": gateway}
    gateway_duration.record(time.perf_counter() - started, attrs)
    charges.add(1, {**attrs, "payment.outcome": outcome})


@app.post("/charge")
def charge(req: Charge):
    gateway = gateway_for(req.card)
    # Chapter 4: our own span, with the details the HTTP instrumentation can't know.
    # Never the card number itself: the brand is enough to answer the question.
    with tracer.start_as_current_span("charge card") as span:
        span.set_attribute("payment.gateway", gateway)
        span.set_attribute("payment.card.brand", brand_of(req.card))
        span.set_attribute("payment.amount", req.amount)
        started = time.perf_counter()
        try:
            call_gateway(gateway)
        except TimeoutError as e:
            # Leaving the with-block with an exception records it on the span and marks it ERROR.
            log.error("order %s: %s", req.order_id, e)
            record_charge(gateway, "timeout", started)
            raise HTTPException(504, f"{gateway} timeout") from e
        record_charge(gateway, "charged", started)
        span.add_event("charged")

    log.info("order %s: charged %d via %s", req.order_id, req.amount, gateway)
    return {"order_id": req.order_id, "status": "charged"}
