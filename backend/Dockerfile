# Playwright's official image ships Chromium and every OS dependency it needs
# pre-installed, which is by far the most reliable way to run headless Chromium
# in a container - installing it manually on a plain python:slim image is a
# recurring source of "missing shared library" failures.
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

ENV MATJAKT_HOST=0.0.0.0
EXPOSE 8000

WORKDIR /app/backend
CMD ["python", "api_server.py"]
