# Build the SPA with Node, serve the static files with unprivileged nginx.
# nginx proxies /api (HTTP + WebSockets) to the backend, so the browser talks
# to one origin and the backend needs no CORS entry for the UI.

FROM node:22.11.0-alpine3.20 AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` when a lockfile is committed, `npm install` until then.
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
COPY . .
ARG VITE_USE_MOCKS=false
ARG VITE_LANGFUSE_URL=http://localhost:3400
ARG VITE_LANGFUSE_PROJECT_ID=product
ENV VITE_USE_MOCKS=${VITE_USE_MOCKS} \
    VITE_LANGFUSE_URL=${VITE_LANGFUSE_URL} \
    VITE_LANGFUSE_PROJECT_ID=${VITE_LANGFUSE_PROJECT_ID}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
