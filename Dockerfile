# StockPulse v2 — API 服务镜像
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libpq5 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY engine/ ./engine/
COPY dashboard/ ./dashboard/
COPY configs/ ./configs/

RUN pip install --no-cache-dir ".[api,mcp]"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/sp-api/system/health || exit 1

CMD ["stockpulse-server"]
