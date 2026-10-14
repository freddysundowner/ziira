"""Errors shared by the kernel, modules and plugins, with HTTP mapping."""


class ZiiraError(Exception):
    """Base error. `status` is the HTTP status the API returns."""

    status = 400
    code = "error"

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details                  # extra fields the API adds to its reply (a list to choose from ...)


class Unauthorized(ZiiraError):
    """No valid credentials: sign in again."""

    status = 401
    code = "unauthorized"


class ChallengeExpired(Unauthorized):
    """The sign-in challenge is too old (or not ours): start again from the password."""

    code = "challenge_expired"


class MfaRequired(Unauthorized):
    """The password was right but this person uses a second factor: the reply carries a short-lived `challenge` to send
    back with the code."""

    code = "mfa_required"


class Forbidden(ZiiraError):
    """Signed in, but without the permission or scope for this action."""

    status = 403
    code = "forbidden"


class MfaSetupRequired(Forbidden):
    """The business requires a second factor of this person and they have not set one up: only the setup calls work."""

    code = "mfa_setup_required"


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


class TooManyRequests(ZiiraError):
    """Too many attempts: try again later."""

    status = 429
    code = "too_many_requests"


class Unavailable(ZiiraError):
    """The platform cannot do this right now (for example, no way to send email): try again later."""

    status = 503
    code = "unavailable"


class ChooseBusiness(ZiiraError):
    """The credentials are right for more than one business: say which one (the reply lists them)."""

    status = 409
    code = "choose_business"


class UnitNotEnabled(ZiiraError):
    """The module or plugin is not enabled for this tenant."""

    status = 404
    code = "unit_not_enabled"


class DependencyError(ZiiraError):
    """A unit cannot be installed, enabled, disabled or removed because of dependencies."""

    status = 409
    code = "dependency_error"
