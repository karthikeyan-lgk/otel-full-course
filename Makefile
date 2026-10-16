.PHONY: up down reset logs order slow-order

up:          ## build and start the whole lab
	docker compose up -d --build

down:        ## stop the lab (keeps nothing; the lab is stateless)
	docker compose down

reset: down up

logs:        ## follow the app services
	docker compose logs -f frontend checkout kitchen payments

order:       ## place one order with a Visa card (fast gateway)
	curl -s -X POST localhost:8080/order -H 'content-type: application/json' \
	  -d '{"pizza":"margherita","card":"4111111111111111"}'; echo

slow-order:  ## place one order with a Mastercard (legacy gateway, sometimes slow)
	curl -s -X POST localhost:8080/order -H 'content-type: application/json' \
	  -d '{"pizza":"pepperoni","card":"5555555555554444"}'; echo
