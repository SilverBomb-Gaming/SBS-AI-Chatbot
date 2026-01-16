"""Reusable decorators that keep route logic tidy."""
from __future__ import annotations

import hmac
from functools import wraps
from typing import Any, Callable, Iterable, Optional

from flask import abort, current_app, g, jsonify, request

from .ratelimit import RateLimiter

JsonResult = tuple[Any, int] | tuple[Any, int, dict[str, Any]] | Any

_rate_limiter = RateLimiter()


def feature_enabled(name: str) -> bool:
    """Return True when the named feature flag is enabled."""

    flags = current_app.config.get("FEATURE_FLAGS")
    if isinstance(flags, dict):
        value = flags.get(name)
        if isinstance(value, bool):
            return value
        if value is not None:
            return bool(value)
    value = current_app.config.get(name)
    return bool(value)


def auth_required() -> bool:
    """Return True when paid/ultimate auth should be enforced."""

    return feature_enabled("FEATURE_AUTH")


def _wants_json() -> bool:
    if request.path.startswith("/api/"):
        return True
    accepts = getattr(request, "accept_mimetypes", None)
    if not accepts:
        return False
    best = accepts.best_match(["application/json", "text/html"])
    if best == "application/json" and accepts[best] > accepts["text/html"]:
        return True
    return False


def _feature_denied_response(behavior: str) -> JsonResult:
    status = 404 if behavior == "hide" else 403
    message = "Resource not found" if behavior == "hide" else "Forbidden"
    if _wants_json():
        return {"error": message}, status
    return message, status, {"Content-Type": "text/plain"}


def _unauthorized_response() -> JsonResult:
    headers = {"WWW-Authenticate": "ApiKey"}
    if _wants_json():
        return {"error": "Unauthorized"}, 401, headers
    headers["Content-Type"] = "text/plain"
    return "Unauthorized", 401, headers


def _api_key_pool() -> set[str]:
    keys = current_app.config.get("X_API_KEYS")
    if isinstance(keys, set):
        return {str(k) for k in keys if str(k)}
    if isinstance(keys, (list, tuple)):
        return {str(k) for k in keys if str(k)}
    fallback = current_app.config.get("API_KEYS")
    if isinstance(fallback, (list, tuple, set)):
        return {str(k) for k in fallback if str(k)}
    return set()


def require_feature(name: str, *, behavior: str = "hide"):
    """Ensure the wrapped route only runs when a feature flag is enabled."""

    if behavior not in {"hide", "forbid"}:
        raise ValueError("behavior must be 'hide' or 'forbid'")

    def decorator(func: Callable[..., JsonResult]):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            if feature_enabled(name):
                return func(*args, **kwargs)
            return _feature_denied_response(behavior)

        return wrapper

    return decorator


def json_endpoint(func: Callable[..., JsonResult]) -> Callable[..., Any]:
    """Ensure JSON responses with standard error handling."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            result = func(*args, **kwargs)
        except ValueError as exc:  # validation error
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pragma: no cover - log unexpected errors
            current_app.logger.exception(
                "Unhandled error in JSON endpoint", exc_info=exc
            )
            return jsonify({"error": "Internal server error"}), 500

        if isinstance(result, tuple):
            payload = result[0]
            status = result[1]
            headers = result[2] if len(result) > 2 else None
            response = jsonify(payload)
            if headers:
                for key, value in headers.items():
                    response.headers[key] = value
            return response, status
        return jsonify(result)

    return wrapper


def rate_limit(
    limit: int, window_seconds: int, identifier: Optional[Callable[[], str]] = None
):
    """Simple decorator that enforces an in-memory request quota."""

    def decorator(func: Callable[..., JsonResult]):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            ident = identifier() if callable(identifier) else None
            if not ident:
                ident = (
                    request.headers.get("X-API-Key")
                    or request.remote_addr
                    or "anonymous"
                )

            allowed = _rate_limiter.check_allow(
                ident, limit=limit, window_seconds=window_seconds
            )
            if not allowed:
                return jsonify({"error": "Too many requests"}), 429
            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_api_key(func: Callable[..., JsonResult]) -> Callable[..., Any]:
    """Protect endpoints that need API key authentication."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        keys = _api_key_pool()
        provided = request.headers.get("X-API-Key", "")
        if not keys or not provided:
            return _unauthorized_response()

        for key in keys:
            if hmac.compare_digest(provided, key):
                g.current_api_key = provided
                return func(*args, **kwargs)
        return _unauthorized_response()

    return wrapper


def require_role(role: str):
    """Ensure the current request has the required role."""

    def decorator(func: Callable[..., JsonResult]):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            roles: Iterable[str] = getattr(g, "current_roles", [])
            if role not in roles:
                abort(403, "Insufficient role permissions")
            return func(*args, **kwargs)

        return wrapper

    return decorator
