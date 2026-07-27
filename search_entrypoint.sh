#!/bin/sh
set -eu

alembic upgrade head
python -m app.search.reindex
exec python -m app.search.service
