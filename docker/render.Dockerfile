# Single-container image for Render: frontend + backend + bot + notification
# worker, run together under supervisord behind one public port. Postgres and
# Redis are expected to be separate managed Render services (DATABASE_URL /
# REDIS_URL). See render.yaml.
#
# Everything runs as the single non-root "app" user, supervisord included.
# Render's container runtime doesn't grant CAP_KILL across UIDs, so a root
# supervisor can't signal non-root children there (it works locally in plain
# Docker, which is more permissive) - same UID throughout avoids that.

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /srv
ARG INTERNAL_API_URL=http://127.0.0.1:8000
ENV NEXT_TELEMETRY_DISABLED=1 INTERNAL_API_URL=$INTERNAL_API_URL
COPY apps/admin-web/package.json apps/admin-web/package-lock.json ./
RUN npm ci
COPY apps/admin-web ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node

RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data

WORKDIR /srv
COPY apps/backend/requirements.lock /srv/backend-requirements.lock
COPY apps/telegram-bot/requirements.lock /srv/bot-requirements.lock
RUN pip install --no-cache-dir -r backend-requirements.lock -r bot-requirements.lock

COPY --chown=app:app apps/backend /srv/backend
COPY --chown=app:app apps/telegram-bot /srv/bot
COPY --from=frontend-build --chown=app:app /srv/.next/standalone /srv/frontend
COPY --from=frontend-build --chown=app:app /srv/.next/static /srv/frontend/.next/static

COPY docker/render/supervisord.conf /srv/supervisord.conf
COPY docker/render/entrypoint.sh /srv/entrypoint.sh
RUN chmod 755 /srv/entrypoint.sh

# Backend and bot talk to each other over localhost inside this one container.
ENV BACKEND_URL=http://127.0.0.1:8000/api/internal
ENV HOSTNAME=0.0.0.0 PORT=3000 NODE_ENV=production

USER app
EXPOSE 3000
CMD ["/srv/entrypoint.sh"]
