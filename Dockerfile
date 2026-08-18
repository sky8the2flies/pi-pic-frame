FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SDL_VIDEODRIVER=dummy

RUN apt-get update && apt-get install -y --no-install-recommends \
      libsdl2-2.0-0 \
      libsdl2-image-2.0-0 \
      libsdl2-ttf-2.0-0 \
      libjpeg62-turbo \
      libpng16-16 \
      zlib1g \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN mkdir -p /app/data/cache

VOLUME ["/app/data"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["picture-frame-headless", "--config", "/app/config.toml"]
