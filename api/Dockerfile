# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY api /app/api
COPY configs /app/configs
COPY offline /app/offline

ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
