# ==============================================================================
# Opsora Agent API — Production Dockerfile
# Edge proxy terminates Shopify webhooks and forwards all other traffic.
# ==============================================================================

FROM python:3.12-slim

# Security: run as non-root user
RUN groupadd --gid 1001 opsora && \
    useradd --uid 1001 --gid opsora --shell /bin/false --create-home opsora

WORKDIR /app

# Install minimal dependency (dotenv for env var loading)
RUN pip install --no-cache-dir python-dotenv==1.1.0

# Copy application code
COPY opsora_server.py ./
COPY agent_router.py ./
COPY billing.py ./
COPY config.py ./
COPY main.py ./
COPY tools.py ./
COPY agent_loop.py ./
COPY mongo_store.py ./
COPY shopify_webhook.py ./
COPY entrypoint.py ./

# Copy static assets
COPY index.html docs.html ./
COPY assets/ ./assets/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSORA_UPSTREAM_PORT=8081

EXPOSE 8080

# Health check — pure stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; r = urlopen('http://localhost:8080/health'); assert r.status == 200" || exit 1

USER opsora

CMD ["python", "entrypoint.py"]
