FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app && chown app:app /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app alembic.ini ./alembic.ini

USER app
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
