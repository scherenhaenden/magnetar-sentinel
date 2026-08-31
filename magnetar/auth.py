"""
magnetar.auth
-------------
Authentication helpers and HTTP Basic Auth security middleware.
"""

from __future__ import annotations

import functools
import hmac
from flask import Response, request

from magnetar.config import DASH_PASS, DASH_USER


def require_auth_response() -> Response:
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Magnetar Sentinel"'},
    )


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return require_auth_response()
        user_ok = hmac.compare_digest(auth.username.encode("utf-8"), DASH_USER.encode("utf-8"))
        pass_ok = hmac.compare_digest(auth.password.encode("utf-8"), DASH_PASS.encode("utf-8"))
        if not (user_ok and pass_ok):
            return require_auth_response()
        return view(*args, **kwargs)
    return wrapper
