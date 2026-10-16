"""Payments: charges the card through one of two gateways.

The bug the course hunts: cards starting with 5 go through the old "legacy-gw" gateway,
which is sometimes very slow and occasionally times out. Nothing in the logs says
"slow" — you find it in the traces.
"""

import logging
import random
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("payments")
logging.basicConfig(level=logging.INFO)

app = FastAPI()


class Charge(BaseModel):
    order_id: str
    amount: int
    card: str


def gateway_for(card: str) -> str:
    return "legacy-gw" if card.startswith("5") else "fastpay"


@app.post("/charge")
def charge(req: Charge):
    gateway = gateway_for(req.card)
    if gateway == "legacy-gw":
        roll = random.random()
        if roll < 0.04:
            time.sleep(3.0)
            log.error("order %s: %s did not answer", req.order_id, gateway)
            raise HTTPException(504, f"{gateway} timeout")
        time.sleep(random.uniform(1.2, 2.0) if roll < 0.30 else random.uniform(0.04, 0.09))
    else:
        time.sleep(random.uniform(0.03, 0.08))

    log.info("order %s: charged %d via %s", req.order_id, req.amount, gateway)
    return {"order_id": req.order_id, "status": "charged"}
