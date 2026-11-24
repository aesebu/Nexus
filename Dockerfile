FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml /app/
COPY app /app/app
COPY alembic.ini /app/
COPY alembic /app/alembic

RUN pip install --no-cache-dir .

RUN groupadd --system nexus && useradd --system --gid nexus --home-dir /app nexus
USER nexus

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
