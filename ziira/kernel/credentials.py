"""Integration credentials (Daraja keys, bank API keys, ...): stored encrypted, read only by the code that needs them.

A secret is a small JSON object (for example {"consumer_key": ..., "consumer_secret": ..., "passkey": ...}). It is
encrypted with the platform's credentials key before it reaches the database, never logged, and never returned by an
API.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.context import get_context
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.security import decrypt, encrypt

PROVIDERS = ("daraja", "bank", "etims", "whatsapp", "email", "sms")


def store_secret(s: Session, *, company_id: UUID, provider: str, label: str, secret: dict[str, Any],
                 config: dict[str, Any] | None = None, branch_id: UUID | None = None,
                 replace: UUID | None = None) -> UUID:
    """Save a secret (replacing an earlier one if `replace` is given). Returns the credential's id."""
    if provider not in PROVIDERS:
        raise ValidationFailed(f"Provider must be one of: {', '.join(PROVIDERS)}")
    if not label.strip():
        raise ValidationFailed("A label is required")
    if not secret:
        raise ValidationFailed("The secret is empty")
    ciphertext = encrypt(json.dumps(secret)).encode()
    user = get_context().user_id
    if replace is not None:
        found = s.execute(text(
            "update kernel.integration_credential set secret_ciphertext = :c, config = cast(:g as jsonb), "
            "label = :l, updated_at = now(), updated_by = :u where id = :i returning id"),
            {"c": ciphertext, "g": json.dumps(config or {}), "l": label.strip(), "u": str(user) if user else None,
             "i": str(replace)}).first()
        if found is None:
            raise NotFound("Credential not found")
        credential_id: UUID = found.id
        audit.record(s, "rotate", "kernel.integration_credential", credential_id, {"provider": provider})
        return credential_id
    credential_id = s.execute(text(
        "insert into kernel.integration_credential (tenant_id, created_by, company_id, branch_id, provider, label, "
        "secret_ciphertext, config) values (kernel.current_tenant(), :u, :co, :b, :p, :l, :c, cast(:g as jsonb)) "
        "returning id"),
        {"u": str(user) if user else None, "co": str(company_id), "b": str(branch_id) if branch_id else None,
         "p": provider, "l": label.strip(), "c": ciphertext, "g": json.dumps(config or {})}).scalar_one()
    audit.record(s, "create", "kernel.integration_credential", credential_id, {"provider": provider, "label": label})
    return credential_id


def read_secret(s: Session, credential_id: UUID) -> dict[str, Any]:
    """The decrypted secret. Only call this from the code that is about to use it."""
    row = s.execute(text("select secret_ciphertext, status from kernel.integration_credential where id = :i"),
                    {"i": str(credential_id)}).first()
    if row is None or row.status != "active":
        raise NotFound("Credential not found or disabled")
    secret: dict[str, Any] = json.loads(decrypt(bytes(row.secret_ciphertext).decode()))
    return secret


def read_config(s: Session, credential_id: UUID) -> dict[str, Any]:
    """The credential's non-secret settings."""
    row = s.execute(text("select config from kernel.integration_credential where id = :i"),
                    {"i": str(credential_id)}).first()
    if row is None:
        raise NotFound("Credential not found")
    config: dict[str, Any] = row.config
    return config


def disable(s: Session, credential_id: UUID) -> None:
    """Stop a credential being used (the secret is kept encrypted for audit until deleted by an operator)."""
    if s.execute(text("update kernel.integration_credential set status = 'disabled', updated_at = now() "
                      "where id = :i returning id"), {"i": str(credential_id)}).first() is None:
        raise NotFound("Credential not found")
    audit.record(s, "disable", "kernel.integration_credential", credential_id)
