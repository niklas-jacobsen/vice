"""The TypeSafe API key. Stored in the system keychain, never in a config file.

Lookup order: the TYPESAFE_API_KEY environment variable, then the keychain.
"""
from __future__ import annotations

import os

SERVICE = "vice-ai"
ACCOUNT = "typesafe-api-key"
ENV = "TYPESAFE_API_KEY"


class MissingKey(RuntimeError):
    pass


def get() -> str:
    if os.environ.get(ENV):
        return os.environ[ENV]
    try:
        import keyring

        key = keyring.get_password(SERVICE, ACCOUNT)
    except Exception as e:  # noqa: BLE001 - no usable keychain backend
        raise MissingKey(f"could not read the keychain ({type(e).__name__}); set {ENV} instead") from e
    if not key:
        raise MissingKey(f"no TypeSafe API key found. Run `vice setup`, or set {ENV}.")
    return key


def source() -> str | None:
    """Where the key would come from, without revealing it."""
    if os.environ.get(ENV):
        return "environment"
    try:
        import keyring

        return "keychain" if keyring.get_password(SERVICE, ACCOUNT) else None
    except Exception:  # noqa: BLE001
        return None


def store(key: str) -> None:
    import keyring

    keyring.set_password(SERVICE, ACCOUNT, key.strip())


def delete() -> None:
    import keyring

    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass
