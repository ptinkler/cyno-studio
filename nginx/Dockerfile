FROM mirror.gcr.io/library/node:26-alpine AS frontend-builder
WORKDIR /build/src/js
COPY src/js/package.json src/js/package-lock.json ./
RUN npm ci
COPY src/js/ ./
RUN npm run build

FROM mirror.gcr.io/library/nginx:alpine
# Links the GHCR package to this repo (so it inherits the repo's visibility and access)
LABEL org.opencontainers.image.source="https://github.com/ptinkler/cyno-studio"
# Pick up Alpine security fixes that are newer than the base image (the scan fails the build on fixable HIGH/CRITICAL).
# UPGRADE_STAMP changes on every CI run so the build cache never reuses an old upgrade layer.
ARG UPGRADE_STAMP=
RUN apk upgrade --no-cache
COPY --from=frontend-builder /build/src/js/dist /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.inc /etc/nginx/security-headers.inc
