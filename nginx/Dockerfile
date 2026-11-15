FROM mirror.gcr.io/library/node:24-alpine AS frontend-builder
WORKDIR /build/src/js
COPY src/js/package.json src/js/package-lock.json* ./
RUN npm install
COPY src/js/ ./
RUN npm run build

FROM mirror.gcr.io/library/nginx:alpine
# Links the GHCR package to this repo (so it inherits the repo's visibility and access)
LABEL org.opencontainers.image.source="https://github.com/ptinkler/cyno-studio"
COPY --from=frontend-builder /build/src/js/dist /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
