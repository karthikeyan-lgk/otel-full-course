"""Places random orders so the dashboards are never empty."""

import os
import random
import time

import requests

FRONTEND_URL = os.environ["FRONTEND_URL"]
RATE = float(os.environ.get("ORDERS_PER_SECOND", "2"))

PIZZAS = ["margherita", "pepperoni", "farmhouse", "quattro formaggi"]
CARDS = ["4111111111111111", "4012888888881881", "5555555555554444", "5105105105105100"]

time.sleep(5)
while True:
    order = {"pizza": random.choice(PIZZAS), "card": random.choice(CARDS)}
    try:
        r = requests.post(f"{FRONTEND_URL}/order", json=order, timeout=10)
        print(r.status_code, order["pizza"], flush=True)
    except requests.RequestException as e:
        print("error", e, flush=True)
    time.sleep(random.expovariate(RATE))
