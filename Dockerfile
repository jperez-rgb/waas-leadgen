# Playwright's official image ships Chromium + every OS-level dependency it
# needs already installed. Fighting apt-get permissions inside a generic
# Python buildpack is a common pain point on PaaS platforms -- this sidesteps
# it entirely. Version pinned to match the playwright package version in
# requirements.txt; bump both together if you ever upgrade.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# This container doesn't run anything automatically on start -- it just stays
# alive so you can open Render's Shell tab and run pipeline commands manually
# (python run.py scrape / grade / find-emails / summary), same as you would
# in a local terminal. This is intentional: auto-running `scrape` on every
# container restart would silently re-burn Google Places API budget every
# time Render redeploys or restarts the service.
CMD ["python", "-c", "import time; print('Worker ready. Open the Shell tab and run python run.py <command>.', flush=True); time.sleep(2147483647)"]
