#!/bin/sh
set -eu

alembic upgrade head
python main.py
