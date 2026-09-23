FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    EUAIACT_CONTENT_DIR=/app/content EUAIACT_LEGAL_DATES=/app/config/legal_dates.yaml

WORKDIR /app
COPY pyproject.toml README.md ./
COPY euaiact ./euaiact
RUN pip install --no-cache-dir ".[postgres]"
COPY content ./content
COPY config ./config

RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000

# TLS is terminated by the reverse proxy in front of the container.
CMD ["python", "-m", "euaiact.cli", "serve", "--host", "0.0.0.0", "--port", "8000", "--proxy", "--forwarded-allow-ips", "*"]
