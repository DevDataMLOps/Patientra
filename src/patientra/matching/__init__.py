"""Governed cross-hospital patient identity resolution."""

from .identity import IdentityConfig, IdentityError, IdentityResult, resolve_identities

__all__ = ["IdentityConfig", "IdentityError", "IdentityResult", "resolve_identities"]
