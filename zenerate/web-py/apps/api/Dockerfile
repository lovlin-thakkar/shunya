FROM python:3.12-slim

WORKDIR /app/apps/api

RUN apt-get update && apt-get install -y libpq-dev gcc curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:/root/.cargo/bin:$PATH"

# Copy the full workspace so uv can resolve all packages
COPY pyproject.toml uv.lock /app/
COPY apps/api /app/apps/api
COPY packages /app/packages

RUN cd /app && uv sync --all-packages

ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=zenapi.config.settings
