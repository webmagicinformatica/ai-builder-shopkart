# The ShopKart Copilot image. Build it from the repo ROOT (it needs shopkart/ and data/):
#   docker build -f labs/deploy/done/Dockerfile -t shopkart-copilot .
# Later labs build their own app with the same file:  --build-arg APP_DIR=labs/tracing/done

# ---- Stage 1: install the packages with uv ----
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
# Packages first: this layer comes from the cache until uv.lock changes.
# --frozen: exactly what the lock file says. --only-group serve: only what the server
# needs (no test tools, no RAG or PDF libraries).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group serve

# ---- Stage 2: the image we ship. No uv, no build leftovers: just Python and the packages ----
FROM python:3.12-slim

# Part 2 (Lambda): the Lambda Web Adapter turns each Lambda event back into a normal
# HTTP request on port 8000. Outside Lambda it does nothing, so this image runs on ECS too.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/.venv /app/.venv

# 2. Then the code, which changes most often.
ARG APP_DIR=labs/deploy/done
COPY shopkart/ shopkart/
COPY data/orders.json data/orders.json
COPY ${APP_DIR}/*.py ./

# 3. Not root. The app writes its spend ledger to /tmp (the only writable place on Lambda).
RUN useradd --create-home app
USER app
ENV SHOPKART_STATE_DIR=/tmp/shopkart AWS_LWA_PORT=8000 AWS_LWA_READINESS_CHECK_PATH=/health

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
# 0.0.0.0: accept connections from outside the container (localhost would reach nobody).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
