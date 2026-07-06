FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY docker/entrypoint.sh docker/run.sh /opt/
RUN chmod +x /opt/entrypoint.sh /opt/run.sh

WORKDIR /app
# Coolify's scheduled tasks exec INTO this running container, so it just needs
# to stay alive. entrypoint clones the repo + sets up git auth, then idles.
# Scheduled tasks then run `/opt/run.sh new normal` (etc.) inside it.
ENTRYPOINT ["/opt/entrypoint.sh"]
