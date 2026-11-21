# The ShopKart Copilot image. Build it from the repo ROOT (it needs shopkart/ and data/):
#   docker build -f labs/deploy/start/Dockerfile -t shopkart-copilot .
# Five TODOs. The finished file is labs/deploy/done/Dockerfile.

# ---- Stage 1: install the packages with uv ----
# TODO 2: start FROM the slim Python 3.12 image (well under 200 MB, not the 1 GB full one),
#         and name this stage "build":   FROM python:3.12-slim AS build
FROM python:3.12 AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1

# TODO 3: packages BEFORE code, so a code change doesn't reinstall everything.
#   COPY only pyproject.toml and uv.lock, then:  RUN uv sync --frozen --only-group serve
#   (--frozen: exactly the lock file. --only-group serve: only what the server needs.)


# ---- Stage 2: the image we ship: just Python and the packages ----
FROM python:3.12-slim

# TODO 5 (Part 2, Lambda): add the Lambda Web Adapter, one line:
#   COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter


WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/.venv /app/.venv

ARG APP_DIR=labs/deploy/start
COPY shopkart/ shopkart/
COPY data/orders.json data/orders.json
COPY ${APP_DIR}/*.py ./

# TODO 4: don't run as root. Add a user called app, and switch to it:
#   RUN useradd --create-home app
#   USER app

ENV SHOPKART_STATE_DIR=/tmp/shopkart AWS_LWA_PORT=8000 AWS_LWA_READINESS_CHECK_PATH=/health
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
# 0.0.0.0: accept connections from outside the container (localhost would reach nobody).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
