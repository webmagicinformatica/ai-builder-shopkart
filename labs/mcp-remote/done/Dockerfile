# The remote ticket MCP server. Build it from the repo ROOT:
#   docker build -f labs/mcp-remote/done/Dockerfile -t shopkart-tickets-mcp .
# The same pattern as the Copilot's image (labs/deploy): slim, packages from the lock, not root.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group mcp-serve   # the MCP SDK, JWT checks, uvicorn, boto3

FROM python:3.12-slim
# On Lambda: turns events into HTTP requests on port 8000 (does nothing elsewhere)
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/.venv /app/.venv

COPY data/tickets.json data/orders.json data/
ARG APP_DIR=labs/mcp-remote/done
COPY ${APP_DIR}/auth.py ${APP_DIR}/ticket_server.py ./

RUN useradd --create-home app
USER app
# Notes and status changes go to /tmp: the only writable place on Lambda, and it doesn't last.
# A real ticket system keeps them in its database.
ENV SHOPKART_TICKET_STATE=/tmp/ticket-state.json PORT=8000 AWS_LWA_PORT=8000 AWS_LWA_READINESS_CHECK_PATH=/health
EXPOSE 8000
CMD ["python", "ticket_server.py"]
