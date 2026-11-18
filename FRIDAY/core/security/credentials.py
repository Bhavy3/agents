"""Secure credential retrieval for FRIDAY.

Follows a defense-in-depth resolution order:
1. Environment variables
2. Local .env file
3. Windows Credential Manager / OS keyring
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import keyring
except ImportError:  # pragma: no cover
    keyring = None


def get_secret(key: str, service: str = "FRIDAY") -> str | None:
    """Retrieve secret by key from environment, .env, or OS credential manager."""
    # 1. Environment variable
    val = os.getenv(key)
    if val:
        return val.strip()

    # 2. Local .env
    env_path = Path(".env")
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key}="):
                        extracted = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if extracted:
                            return extracted
        except OSError:
            pass

    # 3. Windows Credential Manager / OS keyring
    if keyring is not None:
        try:
            secret = keyring.get_password(service, key)
            if secret:
                return secret.strip()
        except Exception:
            pass

    return None
