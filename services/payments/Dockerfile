FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
# opentelemetry-bootstrap adds the instrumentation packages for the libraries installed above.
RUN pip install --no-cache-dir -r requirements.txt && opentelemetry-bootstrap -a install
COPY app.py .
EXPOSE 8003
CMD ["opentelemetry-instrument", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
