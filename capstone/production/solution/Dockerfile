# The production image of the document assistant. Build it from the repo ROOT:
#   docker build -f capstone/production/solution/Dockerfile -t shopkart-docs .
# It's the deploy lab's Dockerfile, plus what RAG needs: the local models and the index,
# both baked in at build time, so a new task never downloads anything before it can answer.

# ---- Stage 1: packages, then the index and the two local models ----
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 HF_HUB_DISABLE_TELEMETRY=1
# The project's own dependencies (fastembed for the local models, pdfplumber for the index)
# plus the serve group (FastAPI, uvicorn, OpenTelemetry, boto3), exactly as uv.lock says.
# Not --only-group serve, as in the labs: that one has no RAG libraries.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group serve

# The index: parse, chunk and embed the policies (local, free), then the keyword index.
COPY shopkart/ shopkart/
COPY data/policies/ data/policies/
COPY data/products/ data/products/
COPY labs/rag/done/ labs/rag/done/
COPY labs/rag-hybrid/done/ labs/rag-hybrid/done/
RUN .venv/bin/python labs/rag/done/ingest.py \
 && .venv/bin/python -c "import sys; sys.path[:0] = ['labs/rag/done', 'labs/rag-hybrid/done']; \
import hybrid; print('keyword index:', hybrid.build_keyword_index(), 'chunks'); hybrid.LocalReranker()"

# ---- Stage 2: what we ship. No uv, no PDFs, no build leftovers ----
FROM python:3.12-slim
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/.shopkart/rag/index.sqlite /app/.shopkart/rag/index.sqlite
COPY --from=build /app/.shopkart/models /app/.shopkart/models

# The code, which changes most often, last. Same folders as the repo, so every import works.
COPY shopkart/ shopkart/
COPY labs/rag/done/*.py labs/rag/done/
COPY labs/rag-hybrid/done/*.py labs/rag-hybrid/done/
COPY labs/loadtest/done/telemetry.py labs/loadtest/done/limits.py labs/loadtest/done/
COPY capstone/doc-assistant/solution/assistant.py capstone/doc-assistant/solution/
COPY capstone/production/solution/*.py capstone/production/solution/

# Not root. The code and the index are read-only for the app; it writes only to /tmp/shopkart.
RUN useradd --create-home app
USER app
ENV SHOPKART_STATE_DIR=/tmp/shopkart HF_HUB_OFFLINE=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
CMD ["uvicorn", "app:app", "--app-dir", "capstone/production/solution", "--host", "0.0.0.0", "--port", "8000"]
