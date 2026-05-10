#!/bin/bash
# Azure Web App Service startup script
# Place this as startup.sh in your backend directory

pip install -r requirements.txt
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
