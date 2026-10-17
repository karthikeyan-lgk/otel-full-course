"""Kitchen: bakes the pizza. Quattro formaggi takes a bit longer, as it should."""

import logging
import random
import time

from flask import Flask, request

log = logging.getLogger("kitchen")
logging.basicConfig(level=logging.INFO)
# Chapter 6: werkzeug logs an access line for every request, which is already a span.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__)

BAKE_SECONDS = {"quattro formaggi": (0.25, 0.40)}


@app.post("/bake")
def bake():
    order = request.get_json()
    low, high = BAKE_SECONDS.get(order["pizza"], (0.08, 0.20))
    time.sleep(random.uniform(low, high))
    log.info("order %s: %s out of the oven", order["order_id"], order["pizza"])
    return {"order_id": order["order_id"], "status": "baked"}
