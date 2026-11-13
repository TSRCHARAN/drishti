# Drishti server: ingestion + query API.
# Build from the repo root:  docker build -f docker/server.Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# The server reuses the SDK's pricing table, so install both packages.
COPY sdk-python/ sdk-python/
COPY server/ server/
RUN pip install --no-cache-dir ./sdk-python ./server

ENV DRISHTI_SERVER_HOST=0.0.0.0 \
    DRISHTI_SERVER_PORT=8787 \
    DRISHTI_DATABASE_URL=sqlite:////data/drishti.db

VOLUME /data
EXPOSE 8787

CMD ["drishti-server"]
