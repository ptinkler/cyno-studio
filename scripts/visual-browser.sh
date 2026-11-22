#!/bin/sh
# The browser for the screenshot tests: Playwright's own Docker image, so the fonts and rasterising behind every
# baseline are the same on every machine and in CI. It shares the host's network, so it reaches the app on
# 127.0.0.1 and the tests connect to it on :3100.   scripts/visual-browser.sh start | stop
set -eu
cd "$(dirname "$0")/.."
NAME=cyno-visual-browser
VERSION=$(node -p "require('./src/js/node_modules/@playwright/test/package.json').version")
case "${1:-}" in
start)
	docker rm -f "$NAME" >/dev/null 2>&1 || true
	docker run -d --rm --name "$NAME" --network host --ipc=host --init "mcr.microsoft.com/playwright:v$VERSION-noble" \
		sh -c "npx -y playwright@$VERSION run-server --host 127.0.0.1 --port 3100" >/dev/null
	for _ in $(seq 1 60); do
		docker logs "$NAME" 2>&1 | grep -q 'Listening on' && exit 0
		sleep 1
	done
	docker logs "$NAME" >&2
	echo "the visual browser did not start" >&2
	exit 1
	;;
stop) docker rm -f "$NAME" >/dev/null 2>&1 || true ;;
*) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
