# Gridglass production image: Python 3.13 slim + gunicorn, runs as a non-root user.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code changes don't reinstall them.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml README.md wsgi.py gunicorn.conf.py ./
COPY gridglass ./gridglass
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 gridglass

USER gridglass

# Uploads only live for an hour, so the container's own disk is enough for a single instance.
ENV PORT=8000 \
    DATA_DIR=/tmp/gridglass \
    TRUST_PROXY=1 \
    WEB_CONCURRENCY=2 \
    POLARS_MAX_THREADS=2

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz', timeout=4)"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
