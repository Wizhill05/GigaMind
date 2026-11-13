#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
npm ci --prefix frontend
npm run build --prefix frontend
python -m pip install -r requirements.txt
