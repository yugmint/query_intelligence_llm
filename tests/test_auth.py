"""
Tests for utils/auth.py::_check_startup_auth.

Tests the extracted validation function directly rather than reloading
the module (which has real side effects -- reading env vars, logging at
import time) -- see the function's own docstring for why this exists.
"""

import pytest

from src.utils.auth import _check_startup_auth


def test_allows_missing_key_in_development():
    # Should not raise -- this is the default local-dev workflow.
    _check_startup_auth(api_key=None, app_env="development")


def test_allows_present_key_in_any_environment():
    _check_startup_auth(api_key="secret", app_env="production")
    _check_startup_auth(api_key="secret", app_env="development")


def test_refuses_missing_key_outside_development():
    with pytest.raises(RuntimeError, match="RAG_API_KEY"):
        _check_startup_auth(api_key=None, app_env="production")


def test_refuses_missing_key_for_any_non_development_value():
    # Not just "production" specifically -- anything other than the
    # literal "development" string should fail closed.
    with pytest.raises(RuntimeError):
        _check_startup_auth(api_key=None, app_env="staging")
