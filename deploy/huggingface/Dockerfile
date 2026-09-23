# Hugging Face Space (Docker SDK) running the EUAIACT demo straight from GitHub.
# Upload this file and README.md to a new Docker Space. To update the demo after changes
# on GitHub, use "Factory rebuild" in the Space settings.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_DIR=/home/user/app

# Spaces run the container as user 1000.
RUN useradd --create-home --uid 1000 user
WORKDIR $APP_DIR

ADD https://github.com/paola-grx/EUAIACT/archive/refs/heads/main.tar.gz /tmp/euaiact.tar.gz
RUN tar -xzf /tmp/euaiact.tar.gz --strip-components=1 -C $APP_DIR \
    && rm /tmp/euaiact.tar.gz \
    && pip install --no-cache-dir . \
    && chown -R user:user $APP_DIR

USER user

# Demo: fictional sample data, SQLite in /tmp (reset on every restart).
# SPACE_HOST, set by Hugging Face, provides the public https address. A random session
# secret is generated per start unless EUAIACT_SECRET_KEY is set as a Space secret.
ENV EUAIACT_DEMO=1 \
    EUAIACT_DATABASE_URL=sqlite:////tmp/euaiact.db \
    EUAIACT_CONTENT_DIR=/home/user/app/content \
    EUAIACT_LEGAL_DATES=/home/user/app/config/legal_dates.yaml \
    PORT=7860

EXPOSE 7860
CMD ["python", "-m", "euaiact.cli", "serve", "--host", "0.0.0.0", "--proxy", "--forwarded-allow-ips", "*"]
