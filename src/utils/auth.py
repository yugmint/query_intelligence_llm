# src/utils/auth.py

import os

from fastapi import Header, HTTPException

from src.utils.logger import logger

_API_KEY_ENV_VAR = "RAG_API_KEY"
_APP_ENV_ENV_VAR = "APP_ENV"


def _check_startup_auth(
    api_key: str | None,
    app_env: str,
    api_key_env_var: str = _API_KEY_ENV_VAR,
) -> None:
    """
    Fail closed, not open: outside a `development` environment, refuse to
    start at all without an API key rather than silently serving
    unauthenticated traffic. `APP_ENV` defaults to "development" so the
    existing no-env-vars-needed local dev workflow keeps working
    unchanged -- production deployments must set APP_ENV explicitly (to
    anything other than "development") to opt into this check, at which
    point a missing key is a startup-time RuntimeError, not a runtime
    surprise. Found necessary via a real deployment-readiness review:
    the previous behavior (warn-and-allow always) meant a single missing
    env var in deployment config silently gave public, unauthenticated
    access to every endpoint. See docs/05-roadmap.md.
    """

    if api_key:
        return

    if app_env != "development":
        raise RuntimeError(
            f"{api_key_env_var} is not set and {_APP_ENV_ENV_VAR}={app_env!r} "
            f"(not 'development') -- refusing to start unauthenticated in a "
            f"non-dev environment. Set {api_key_env_var}, or explicitly set "
            f"{_APP_ENV_ENV_VAR}=development if this really is local dev."
        )

    logger.warning(
        f"{api_key_env_var} is not set -- /query, /reload, and "
        f"/reset-memory are running UNAUTHENTICATED. This is only allowed "
        f"because {_APP_ENV_ENV_VAR}=development (the default). Set "
        f"{api_key_env_var} before deploying anywhere else -- this will "
        f"refuse to start without it outside a dev environment."
    )


_API_KEY = os.getenv(_API_KEY_ENV_VAR)
_check_startup_auth(_API_KEY, os.getenv(_APP_ENV_ENV_VAR, "development"))


def require_api_key(x_api_key: str | None = Header(default=None)):
    """
    FastAPI dependency enforcing a shared-secret API key via the
    X-API-Key header. A no-op (allows everything) only if RAG_API_KEY
    isn't configured *and* APP_ENV=development -- see
    `_check_startup_auth` above, which refuses to even start otherwise.

    Intentionally minimal: one shared key, no per-client identity, no
    rotation. Enough to stop casual/accidental unauthenticated access;
    not a substitute for a real auth layer (OAuth, per-user keys, a
    gateway) before this is exposed to untrusted traffic. See
    docs/05-roadmap.md.
    """

    if _API_KEY is None:
        return

    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
