FROM mirror.gcr.io/library/node:24-alpine AS frontend-builder
WORKDIR /build/src/js
COPY src/js/package.json src/js/package-lock.json* ./
RUN npm install
COPY src/js/ ./
RUN npm run build

FROM mirror.gcr.io/library/nginx:alpine
COPY --from=frontend-builder /build/src/py/web/static /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
