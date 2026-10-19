"""Photos and documents on a claim, and the ones shown to the payer on the response link.

The claim is an attachable record (`claims.claim`, see hooks.py). A file marked *shareable* on the claim, or on the
job or
appointment it is for, appears on the payer's response page; staff-only files never do. The addresses are short-lived
and
signed (the files service), every full-size opening is logged there with the label below, and they are ended at once
when a
link is revoked or signed off."""

from typing import Any
from uuid import UUID

from ziira.modules.claims.repository.models import Claim
from ziira.sdk import NotFound, Session, ValidationFailed, files

CLAIM_ENTITY = "claims.claim"
SOURCE_ENTITIES = {"job": "jobs.job", "appointment": "bookings.appointment"}


def _records(claim: Claim) -> list[tuple[str, UUID]]:
    found = [(CLAIM_ENTITY, claim.id)]
    kind = SOURCE_ENTITIES.get(claim.source_type or "")
    if kind and claim.source_id:
        found.append((kind, claim.source_id))
    return found


def shareable_files(session: Session, claim: Claim, *, seconds: int = 1800) -> list[dict[str, Any]]:
    """Shareable files for the payer's page: `{id, category, caption, kind, name, thumb, web, original}` with
    addresses that
    work without an account until they end. Records whose unit is switched off are skipped."""
    out: list[dict[str, Any]] = []
    for entity_type, entity_id in _records(claim):
        try:
            shown = files.public_links(session, entity_type, entity_id, label=f"insurer response {claim.number}",
                                       seconds=seconds)
        except (NotFound, ValidationFailed):
            continue
        out += [{"id": str(f.id), "category": f.category, "caption": f.caption, "kind": f.kind, "name": f.name,
                 "thumb": f.thumb.path if f.thumb else None, "web": f.web.path if f.web else None,
                 "original": f.original.path} for f in shown]
    return out


def end_addresses(session: Session, claim: Claim) -> None:
    """Stop every address made for the claim's shareable files (a link was revoked, signed off or replaced)."""
    for entity_type, entity_id in _records(claim):
        try:
            files.revoke_links_for_entity(session, entity_type, entity_id)
        except Exception:        # the record's unit is off, or the person may not edit its files: best effort
            continue
