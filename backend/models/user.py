"""Compatibility import for services that use the historical User name."""

from .app_user import AppUser as User

__all__ = ["User"]
