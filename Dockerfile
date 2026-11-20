FROM python:3.11-slim

ARG ENABLE_SEMANTIC=0
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8000 \
    REQUIRE_API_KEY=1 \
    ATLAS_DEV_TOOLS=0 \
    ATLAS_CACHE_DIR=/app/.cache \
    HF_HOME=/app/.cache/huggingface \
    TORCH_HOME=/app/.cache/torch \
    ATLAS_BUILD_SEMANTIC=${ENABLE_SEMANTIC} \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1

WORKDIR /app
RUN python -m venv /opt/venv \
    && useradd --create-home --uid 10001 atlas \
    && mkdir -p /app/data /app/.cache \
    && chown atlas:atlas /app /app/data /app/.cache
COPY requirements.txt requirements-semantic.txt ./
RUN pip install --no-cache-dir --require-virtualenv -r requirements.txt \
    && if [ "$ENABLE_SEMANTIC" = "1" ]; then \
         pip install --no-cache-dir --require-virtualenv --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 \
         && pip install --no-cache-dir --require-virtualenv -r requirements-semantic.txt; \
       fi

COPY --chown=atlas:atlas app ./app
COPY --chown=atlas:atlas static ./static
COPY --chown=atlas:atlas data/raw ./data/raw
USER atlas
# CSV -> index is reproduced inside the image. No host database or .venv is copied.
RUN python -m app ingest \
    && if [ "$ENABLE_SEMANTIC" = "1" ]; then python -m app embed --model "$EMBEDDING_MODEL"; fi

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/healthz',timeout=3)"
CMD ["python", "-m", "app", "serve", "--production", "--host", "0.0.0.0"]
