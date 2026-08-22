FROM python:3.12-slim

WORKDIR /app

# Install deps first so Docker layer-caches them across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# Single worker on purpose: session state (DuckDB connections) is in-process.
# See README "Scaling notes" for the Redis/file-backed path to multi-worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
