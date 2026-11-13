# Veekshana server: ingestion + query API.
# Build from the repo root:  docker build -f docker/server.Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# The server reuses the SDK's pricing table, so install both packages.
COPY sdk-python/ sdk-python/
COPY server/ server/
RUN pip install --no-cache-dir ./sdk-python ./server

ENV VEEKSHANA_SERVER_HOST=0.0.0.0 \
    VEEKSHANA_SERVER_PORT=8787 \
    VEEKSHANA_DATABASE_URL=sqlite:////data/veekshana.db

VOLUME /data
EXPOSE 8787

CMD ["veekshana-server"]
