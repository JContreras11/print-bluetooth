#!/bin/zsh
# Lanza el servidor de la interfaz web de la Y50
cd "$(dirname "$0")"
python3 server.py "$@"
