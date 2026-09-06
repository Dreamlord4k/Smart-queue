FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/backend

WORKDIR /workspace

COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt

COPY backend ./backend

WORKDIR /workspace/backend

EXPOSE 8000

CMD ["sh", "-c", "alembic -c /workspace/backend/alembic.ini upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
