"""Checkout: prices the order, charges the card, sends it to the kitchen, saves it."""

import logging
import os
import uuid
from contextlib import asynccontextmanager

import httpx
import psycopg
import redis
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from opentelemetry import trace
from pydantic import BaseModel

log = logging.getLogger("checkout")
logging.basicConfig(level=logging.INFO)
# Chapter 6: httpx logs an INFO line for every outgoing call, which is already a span.
logging.getLogger("httpx").setLevel(logging.WARNING)

DATABASE_URL = os.environ["DATABASE_URL"]
KITCHEN_URL = os.environ["KITCHEN_URL"]
PAYMENTS_URL = os.environ["PAYMENTS_URL"]
# Chapter 11: any OpenAI-compatible endpoint. No key, no suggestions; the rest of the shop doesn't care.
LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "mistralai/mistral-nemo")
llm = OpenAI(base_url=os.environ.get("LLM_BASE_URL"), api_key=LLM_API_KEY) if LLM_API_KEY else None

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
    # Chapter 4: enrich the span FastAPI already started, instead of making a new one.
    span = trace.get_current_span()
    span.set_attribute("order.id", order_id)
    span.set_attribute("order.pizza", order.pizza)
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


@app.get("/suggest")
def suggest(pizza: str):
    # Chapter 11: one model call. The openai instrumentation that opentelemetry-bootstrap installed
    # turns it into a gen_ai span with the model, the token counts and how long it took.
    if llm is None:
        raise HTTPException(503, "set LLM_API_KEY to get suggestions")
    if pizza not in MENU:
        raise HTTPException(404, f"no such pizza: {pizza}")
    resp = llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "You work at Slice Shop. Answer with one topping, nothing else."},
            {"role": "user", "content": f"What one extra topping goes best on a {pizza} pizza?"},
        ],
        max_tokens=10,
    )
    topping = resp.choices[0].message.content.strip()
    log.info("suggested %s for %s", topping, pizza)
    return {"pizza": pizza, "topping": topping}
