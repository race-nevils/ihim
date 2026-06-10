"""HTTP middleware: security headers, CSP, cache-control, request timeout.

The dashboard is same-origin (UI served by this server) and the app has no
WebSockets — SSE and fetch are covered by connect-src 'self' — so the CSP
needs no port-specific entries and works unchanged on 7777, 7778, or any
test port. Report-only while the new UI stabilizes; flip to enforcing by
renaming the header once the browser console shows zero violations.
"""

import asyncio
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 30.0

# 'unsafe-inline' in script-src exists for the <script type="importmap"> block,
# which the HTML spec requires to be inline and which embeds the per-boot cache
# version. All other scripts are external modules under /static/.
_CSP_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
])

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy-Report-Only": _CSP_POLICY,
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=()",
}

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def register_middleware(app) -> None:
    """Attach all HTTP middleware to the app."""

    @app.middleware("http")
    async def security_and_cache_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        if request.url.path.startswith(("/api/", "/static/")) or request.url.path == "/":
            response.headers.update(_NO_CACHE_HEADERS)
        return response

    @app.middleware("http")
    async def request_timeout(request: Request, call_next):
        """Convert event-loop stalls into a 504 instead of hanging forever.

        SSE streams (text/event-stream) are exempt — they are long-lived by
        design. The timeout wraps the handler that *returns* the streaming
        response, not the stream itself, but exempting them keeps slow
        first-byte cases unambiguous.
        """
        if request.url.path.endswith("/stream"):
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.error("Request timed out after %.0fs: %s %s",
                         REQUEST_TIMEOUT_S, request.method, request.url.path)
            return JSONResponse(
                status_code=504,
                content={
                    "type": "about:blank",
                    "title": "Gateway Timeout",
                    "status": 504,
                    "detail": f"Request timed out after {REQUEST_TIMEOUT_S:.0f} seconds",
                    "instance": str(request.url.path),
                },
                media_type="application/problem+json",
            )
