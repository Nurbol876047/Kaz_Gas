#!/bin/sh
set -e

cd /srv/backend
su -s /bin/sh app -c "alembic upgrade head"

exec supervisord -n -c /etc/supervisor/supervisord.conf
