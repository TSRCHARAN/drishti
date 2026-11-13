# Drishti web UI (Next.js, standalone output).
# Build from the repo root:  docker build -f docker/web.Dockerfile .
#
# NEXT_PUBLIC_* values are baked into the client bundle at BUILD time.
# The host must be reachable from the viewer's browser (default: localhost:8787).
FROM node:22-alpine AS build

WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY web/ .
ARG NEXT_PUBLIC_DRISHTI_HOST=http://localhost:8787
ARG NEXT_PUBLIC_DRISHTI_API_KEY=dev-key
ENV NEXT_PUBLIC_DRISHTI_HOST=$NEXT_PUBLIC_DRISHTI_HOST \
    NEXT_PUBLIC_DRISHTI_API_KEY=$NEXT_PUBLIC_DRISHTI_API_KEY \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine

WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
