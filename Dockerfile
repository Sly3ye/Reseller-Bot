# Backend Reseller Bot (FastAPI + scheduler + scraper).
FROM python:3.12-slim

# Dipendenze di sistema minime per Pillow/imagehash (decodifica JPEG/PNG/WEBP).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# Script operativi (seed della flotta, merge tra istanze) eseguibili in-container
# via `docker compose exec backend python scripts/<nome>.py`.
COPY scripts/ ./scripts/

# Le immagini scaricate vivono qui (montato come volume in docker-compose).
ENV MEDIA_ROOT=/data/media
RUN mkdir -p /data/media

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
