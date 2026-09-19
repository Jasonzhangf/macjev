"""Explicit errors for the MacJev experiment."""


class MacJevError(Exception):
    """Base class for expected service failures."""

    error_type = "macjev_error"


class SchemaError(MacJevError):
    """The request does not satisfy the supported decision schema."""

    error_type = "schema_error"


class UnsupportedFeature(MacJevError):
    """The request uses a feature not supported by this backend."""

    error_type = "unsupported_feature"


class BackendError(MacJevError):
    """The inference backend failed or returned an invalid response."""

    error_type = "backend_error"
