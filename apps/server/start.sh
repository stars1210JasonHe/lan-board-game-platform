#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "Starting LAN Board Game Platform..."
node dist/index.js
