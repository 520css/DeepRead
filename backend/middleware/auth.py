"""No-auth middleware: injects a default local user into every request.

Personal local use — no OAuth, no tokens, no Stripe.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


LOCAL_USER = {"id": "local", "email": "user@local", "name": "Local User"}


class NoAuthMiddleware(BaseHTTPMiddleware):
    """Inject request.state.user = LOCAL_USER on every request."""

    async def dispatch(self, request: Request, call_next):
        request.state.user = LOCAL_USER
        response = await call_next(request)
        return response
