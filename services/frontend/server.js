// Frontend: takes the order from the customer and hands it to checkout.
import express from "express";

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
  res.status(resp.status).json(await resp.json());
});

app.listen(8080, () => console.log("frontend listening on :8080"));
