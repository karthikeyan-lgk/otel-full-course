.PHONY: up down reset logs order slow-order k8s-up k8s-ui k8s-down

up:          ## build and start the whole lab
	docker compose up -d --build

down:        ## stop the lab (keeps nothing; the lab is stateless)
	docker compose down

reset: down up

logs:        ## follow the app services
	docker compose logs -f frontend checkout kitchen payments

order:       ## place one order with a Visa card (fast gateway)
	@curl -s -X POST localhost:8080/order -H 'content-type: application/json' \
	  -d '{"pizza":"margherita","card":"4111111111111111"}'; echo

slow-order:  ## place one order with a Mastercard (legacy gateway, sometimes slow)
	@curl -s -X POST localhost:8080/order -H 'content-type: application/json' \
	  -d '{"pizza":"pepperoni","card":"5555555555554444"}'; echo

# Chapter 9: the same shop on Kubernetes (kind), instrumented by the OpenTelemetry Operator.
# Needs kind, kubectl and helm. Uses about 3 GB of RAM; stop the docker-compose lab first (make down).
K8S_IMAGES := frontend checkout kitchen payments loadgen
OPERATOR_CHART := 0.126.0

k8s-up:      ## kind cluster + Operator + Collectors + Jaeger/Prometheus + the shop
	kind create cluster --config k8s/kind.yaml
	# Two nodes, and the shop may run on both, so each node's agent has work to do.
	kubectl taint nodes slice-shop-control-plane node-role.kubernetes.io/control-plane:NoSchedule-
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
	helm install opentelemetry-operator open-telemetry/opentelemetry-operator --version $(OPERATOR_CHART) \
	  -n opentelemetry-operator-system --create-namespace --wait \
	  --set admissionWebhooks.certManager.enabled=false --set admissionWebhooks.autoGenerateCert.enabled=true \
	  --set manager.collectorImage.repository=otel/opentelemetry-collector-contrib \
	  --set manager.collectorImage.tag=0.162.0
	for s in $(K8S_IMAGES); do docker build -q -t slice-shop/$$s:lab services/$$s; done
	kind load docker-image --name slice-shop $(addprefix slice-shop/,$(addsuffix :lab,$(K8S_IMAGES)))
	kubectl apply -f k8s/backends.yaml -f k8s/collectors.yaml -f k8s/instrumentation.yaml
	kubectl rollout status deploy/gateway-collector -n otel --timeout=180s
	# The Instrumentation must exist before the shop's pods are created: injection happens at pod creation.
	kubectl apply -f k8s/shop.yaml
	kubectl wait --for=condition=Available deploy --all -n slice-shop --timeout=300s

k8s-ui:      ## forward the shop, Jaeger and Prometheus to the usual localhost ports (Ctrl+C to stop)
	kubectl port-forward -n slice-shop svc/frontend 8080:8080 & \
	kubectl port-forward -n observability svc/jaeger 16686:16686 & \
	kubectl port-forward -n observability svc/prometheus 9090:9090

k8s-down:    ## delete the kind cluster
	kind delete cluster --name slice-shop
