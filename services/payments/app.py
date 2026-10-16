"""Payments: charges the card through one of two gateways.

The bug the course hunts: cards starting with 5 go through the old "legacy-gw" gateway,
which is sometimes very slow and occasionally times out. Nothing in the logs says
"slow" — you find it in the traces.
"""

import logging
import random
import time

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from pydantic import BaseModel

log = logging.getLogger("payments")
tracer = trace.get_tracer("slice-shop.payments")
logging.basicConfig(level=logging.INFO)

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


@app.post("/charge")
def charge(req: Charge):
    gateway = gateway_for(req.card)
    # Chapter 4: our own span, with the details the HTTP instrumentation can't know.
    # Never the card number itself: the brand is enough to answer the question.
    with tracer.start_as_current_span("charge card") as span:
        span.set_attribute("payment.gateway", gateway)
        span.set_attribute("payment.card.brand", brand_of(req.card))
        span.set_attribute("payment.amount", req.amount)
        try:
            call_gateway(gateway)
        except TimeoutError as e:
            # Leaving the with-block with an exception records it on the span and marks it ERROR.
            log.error("order %s: %s", req.order_id, e)
            raise HTTPException(504, f"{gateway} timeout") from e
        span.add_event("charged")

    log.info("order %s: charged %d via %s", req.order_id, req.amount, gateway)
    return {"order_id": req.order_id, "status": "charged"}
