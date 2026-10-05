FROM python:3.14.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-treinamento.txt requirements-backend.txt ./
RUN python -m pip install --no-cache-dir -r requirements-backend.txt

COPY backend/ ./backend/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
