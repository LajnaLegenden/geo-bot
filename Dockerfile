FROM python:3.12-slim

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

# SQLite (and any cached data) lives on a persistent volume; state is no longer
# in git. Single process on purpose: Flask + APScheduler in one waitress server,
# so scheduled jobs fire exactly once (a multi-worker server would fire N times).
ENV GEO_DB=/data/geobot.db
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "-m", "geobot.serve"]
