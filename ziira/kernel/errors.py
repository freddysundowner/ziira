"""Errors shared by the kernel, modules and plugins, with HTTP mapping."""


class ZiiraError(Exception):
    """Base error. `status` is the HTTP status the API returns."""

    status = 400
    code = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ZiiraError):
    """The requested record does not exist for this tenant."""

    status = 404
    code = "not_found"


class ValidationFailed(ZiiraError):
    """Input breaks a business rule."""

    status = 422
    code = "validation_failed"


class Conflict(ZiiraError):
    """The record already exists or the action conflicts with current state."""

    status = 409
    code = "conflict"


class UnitNotEnabled(ZiiraError):
    """The module or plugin is not enabled for this tenant."""

    status = 404
    code = "unit_not_enabled"


class DependencyError(ZiiraError):
    """A unit cannot be installed, enabled, disabled or removed because of dependencies."""

    status = 409
    code = "dependency_error"
