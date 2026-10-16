"""Checkout: prices the order, charges the card, sends it to the kitchen, saves it."""

import logging
import os
import uuid
from contextlib import asynccontextmanager

import httpx
import psycopg
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("checkout")
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ["DATABASE_URL"]
KITCHEN_URL = os.environ["KITCHEN_URL"]
PAYMENTS_URL = os.environ["PAYMENTS_URL"]

MENU = {"margherita": 299, "pepperoni": 399, "farmhouse": 449, "quattro formaggi": 499}
cache = redis.Redis(host="redis", decode_responses=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS orders ("
            " id TEXT PRIMARY KEY, pizza TEXT NOT NULL, price INTEGER NOT NULL,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    yield


app = FastAPI(lifespan=lifespan)


class Order(BaseModel):
    pizza: str
    card: str


def price_of(pizza: str) -> int:
    cached = cache.get(f"price:{pizza}")
    if cached is not None:
        return int(cached)
    if pizza not in MENU:
        raise HTTPException(404, f"no such pizza: {pizza}")
    cache.set(f"price:{pizza}", MENU[pizza], ex=30)
    return MENU[pizza]


@app.post("/checkout")
def checkout(order: Order):
    order_id = uuid.uuid4().hex[:8]
    price = price_of(order.pizza)

    payment = httpx.post(
        f"{PAYMENTS_URL}/charge",
        json={"order_id": order_id, "amount": price, "card": order.card},
        timeout=5,
    )
    if payment.status_code != 200:
        log.error("order %s: payment failed (%s)", order_id, payment.text)
        raise HTTPException(502, "payment failed")

    httpx.post(f"{KITCHEN_URL}/bake", json={"order_id": order_id, "pizza": order.pizza}, timeout=5)

    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO orders (id, pizza, price) VALUES (%s, %s, %s)",
            (order_id, order.pizza, price),
        )

    log.info("order %s placed: %s for %d", order_id, order.pizza, price)
    return {"order_id": order_id, "pizza": order.pizza, "price": price}
