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


class ModelNotFound(MacJevError):
    """The requested public model alias is not available."""

    error_type = "not_found_error"


class BackendError(MacJevError):
    """The inference backend failed or returned an invalid response."""

    error_type = "backend_error"


class ConfigError(MacJevError):
    """The MacJev runtime configuration is missing or invalid."""

    error_type = "config_error"


class DaemonError(MacJevError):
    """The managed inference daemon failed to start, stop, or report health."""

    error_type = "daemon_error"
