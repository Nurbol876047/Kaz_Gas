#!/bin/sh
set -e

cd /srv/backend
su -s /bin/sh app -c "alembic upgrade head"
su -s /bin/sh app -c "python -m app.bootstrap_admin"

exec supervisord -n -c /etc/supervisor/supervisord.conf
