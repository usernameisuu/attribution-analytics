FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY uv.lock ./
COPY app ./app
COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /uvx /bin/
RUN uv sync --locked --no-dev --no-editable && useradd --uid 10001 --create-home appuser
ENV PATH="/app/.venv/bin:$PATH"
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
