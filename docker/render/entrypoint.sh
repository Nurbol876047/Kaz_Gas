#!/bin/sh
set -e

cd /srv/backend
alembic upgrade head
python -m app.bootstrap_admin

exec supervisord -c /srv/supervisord.conf
