FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY crawler/ ./crawler/
COPY main.py ./

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uv run uvicorn crawler.api.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
