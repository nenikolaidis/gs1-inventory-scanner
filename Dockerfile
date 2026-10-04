# --- build the web app ---
FROM node:24-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Vite writes the build to ../src/gs1_scanner/server/static
RUN npm run build

# --- Python server ---
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GS1_SCANNER_HOME=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE.md ./
COPY src ./src
COPY --from=web /app/src/gs1_scanner/server/static ./src/gs1_scanner/server/static
RUN pip install ".[postgres]" \
    && useradd --system --uid 1000 --home /data app \
    && mkdir -p /data && chown app /data

USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["gs1-scanner", "serve", "--host", "0.0.0.0", "--port", "8000"]
