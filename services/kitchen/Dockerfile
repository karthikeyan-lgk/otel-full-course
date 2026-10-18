FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
# opentelemetry-bootstrap adds the instrumentation packages for the libraries installed above.
RUN pip install --no-cache-dir -r requirements.txt && opentelemetry-bootstrap -a install
COPY app.py otel.yaml ./
EXPOSE 8002
CMD ["opentelemetry-instrument", "flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "8002"]
