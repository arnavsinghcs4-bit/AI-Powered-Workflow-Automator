"""Tests to catch import-time failures."""

import pytest


def test_app_main_imports_without_error():
    """Test that app.main can be imported with test environment set."""
    # This import will trigger the lifespan startup which validates encryption
    # If SECRETS_ENCRYPTION_KEY is not set in conftest.py, this would fail
    from app.main import app

    assert app is not None


def test_credentials_service_imports():
    """Test that credentials service imports without error."""
    from app.credentials.service import get_encryption

    encryption = get_encryption()
    assert encryption is not None
    # Should be a MultiFernet instance (from cryptography.fernet)
    from cryptography.fernet import MultiFernet
    assert isinstance(encryption, MultiFernet)