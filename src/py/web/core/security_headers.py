"""Response headers that limit what a page, or a file opened on its own, can do.

The page (the SPA) gets a Content-Security-Policy: scripts only from this origin, and pictures only from
here or a few avatar hosts. Replies are rendered from model output, so without it a reply holding
`![](https://elsewhere/?q=…)` would make the browser send that address whatever it likes. Uploaded and
generated files are served with a sandbox, so a stray `.svg` or `.html` opened directly can't run script.

This is the app's own defence for what it serves, whatever sits in front of it.
"""

from typing import cast

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Profile pictures the sign-in providers hand back (the only pictures that don't come from this server)
AVATAR_HOSTS = "https://lh3.googleusercontent.com https://pbs.twimg.com"

PAGE_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",  # components bind inline styles
        f"img-src 'self' data: blob: {AVATAR_HOSTS}",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

FILE_CSP = "default-src 'none'; sandbox"

FILE_PREFIXES = ("/api/chat/media/", "/api/media/", "/api/public-media/")
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")  # the interactive API docs load their scripts from a CDN


def csp_for(path: str) -> str | None:
    """The policy for a response at `path`: a sandbox for a served file, none for the API docs."""
    if path.startswith(FILE_PREFIXES):
        return FILE_CSP
    return None if path in DOC_PATHS else PAGE_CSP


class SecurityHeadersMiddleware:
    """Add the security headers to every HTTP response that doesn't already set them."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the ASGI app this middleware sits in front of."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Set the headers as the response starts."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        csp = csp_for(cast("str", scope.get("path", "")))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "same-origin")
                if csp:
                    headers.setdefault("Content-Security-Policy", csp)
            await send(message)

        await self.app(scope, receive, send_with_headers)
