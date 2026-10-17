// Frontend: takes the order from the customer and hands it to checkout.
import express from "express";
import { createRequire } from "node:module";

// Chapter 6: a real logger instead of console.log. The pino instrumentation that zero-code
// already loaded sends every line to OpenTelemetry, with the trace and span ids attached.
// --require only hooks require(), and this file is an ES module, so an `import pino` would
// never be seen. Loading pino through require() lets the hook find it.
const require = createRequire(import.meta.url);
const pino = require("pino");
const log = pino();

const app = express();
app.use(express.json());

const CHECKOUT_URL = process.env.CHECKOUT_URL;

app.get("/", (req, res) => res.send("Slice Shop is open. POST /order {pizza, card}\n"));

app.post("/order", async (req, res) => {
  const resp = await fetch(`${CHECKOUT_URL}/checkout`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req.body),
  });
  const body = await resp.json();
  if (resp.ok) {
    log.info({ order_id: body.order_id, pizza: req.body.pizza }, "order placed");
  } else {
    log.warn({ status: resp.status, pizza: req.body.pizza }, "order failed");
  }
  res.status(resp.status).json(body);
});

app.listen(8080, () => log.info("frontend listening on :8080"));
