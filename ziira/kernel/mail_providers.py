"""The email providers the Super Admin offers for the platform's own mail (registration, password resets, billing).

A provider here is only a *description*: which fields the owner fills in (host, port, API key ...) and how they
become the `secret` and `config` the sending channel expects. The sending itself is a notification channel (the
messaging plugin registers `smtp`, `brevo`, `resend`, `sendgrid`); a provider is offered only when its channel is
installed.

To add a provider: write its channel (see `docs/writing-a-plugin.md`), then `register(MailProvider(...))` below. Nothing
else changes: the page, the validation, the encryption and the log work from this description.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ziira.kernel.errors import ValidationFailed


@dataclass(frozen=True)
class MailField:
    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    default: str = ""
    options: tuple[str, ...] = ()          # a closed list of values (shown as a choice)
    kind: str = "text"                     # text | number


@dataclass(frozen=True)
class MailProvider:
    name: str                              # the channel's name
    label: str
    description: str
    fields: tuple[MailField, ...]
    dns_hint: str = ""                     # advice text only: nothing is looked up
    build: Callable[[dict[str, str], dict[str, str]], dict[str, Any]] = field(default=lambda values, secrets: {})

    def check_values(self, values: dict[str, str]) -> dict[str, str]:
        """Validate the plain fields (a choice must be one of its options, a number a number)."""
        by_name = {f.name: f for f in self.fields if not f.secret}
        for key in values:
            if key not in by_name:
                raise ValidationFailed(f"'{key}' is not a setting of {self.label}")
        out = {f.name: str(values.get(f.name, f.default)).strip() for f in by_name.values()}
        for f in by_name.values():
            value = out[f.name]
            if len(value) > 300:
                raise ValidationFailed(f"{f.label} is too long")
            if value and f.options and value not in f.options:
                raise ValidationFailed(f"{f.label} is one of: {', '.join(f.options)}")
            if value and f.kind == "number" and (not value.isdigit() or not 1 <= int(value) <= 65535):
                raise ValidationFailed(f"{f.label} is a number from 1 to 65535")
        return out


def _smtp(values: dict[str, str], secrets: dict[str, str]) -> dict[str, Any]:
    return {"secret": {"host": values["host"], "port": int(values["port"] or 587),
                       "username": values.get("username", ""), "password": secrets.get("password", "")},
            "config": {"security": values.get("security") or "starttls"}}


def _api_key(values: dict[str, str], secrets: dict[str, str]) -> dict[str, Any]:
    return {"secret": {"api_key": secrets.get("api_key", "")}, "config": {}}


_API_KEY = MailField("api_key", "API key", secret=True,
                     help="Create a key that may send mail; it is shown only once there")

_PROVIDERS: dict[str, MailProvider] = {}


def register(provider: MailProvider) -> MailProvider:
    """Make a provider available to the Super Admin."""
    _PROVIDERS[provider.name] = provider
    return provider


def get(name: str) -> MailProvider | None:
    return _PROVIDERS.get(name)


def all_providers() -> list[MailProvider]:
    return list(_PROVIDERS.values())


register(MailProvider(
    "smtp", "SMTP server", "Any mail server you can log in to.",
    (MailField("host", "Server", help="For example mail.example.com"),
     MailField("port", "Port", default="587", kind="number", help="587 for STARTTLS, 465 for SSL"),
     MailField("security", "Security", default="starttls", options=("starttls", "ssl", "none"),
               help="STARTTLS upgrades a normal connection; SSL is encrypted from the start; none is for a "
                    "trusted local relay"),
     MailField("username", "Username", required=False),
     MailField("password", "Password", secret=True, required=False)),
    "Publish SPF and DKIM for the sending domain at your mail host, and send from an address on that domain.", _smtp))
for _name, _label, _text in (
        ("brevo", "Brevo", "Transactional email through Brevo. The sender must be a verified sender there."),
        ("resend", "Resend", "Email through Resend. The sender's domain must be verified there."),
        ("sendgrid", "SendGrid", "Email through SendGrid. The sender must be a verified sender or domain there.")):
    register(MailProvider(_name, _label, _text, (_API_KEY,),
                          f"Verify the sending domain in {_label} (it gives you the SPF and DKIM records to publish).",
                          _api_key))
