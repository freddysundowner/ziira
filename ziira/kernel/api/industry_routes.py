"""Industry packs: what a pack added to this business, and removing what nobody has touched (after switching it off).
Needs 'units.manage'. See docs/industry-packs.md."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ziira.kernel import audit, industry, unit_admin
from ziira.kernel.registry import Registry, discover
from ziira.sdk import DB_SESSION, Session, require_permission

router = APIRouter(prefix="/api/v1/industry", tags=["Industry packs"],
                   dependencies=[Depends(require_permission(unit_admin.PERMISSION))])


class IndustrySeededOut(BaseModel):
    seeder: str
    item_type: str
    item_id: UUID
    label: str
    untouched: bool = Field(description="Still as the pack made it and unused: removing it loses nothing")


class IndustryRemovedOut(BaseModel):
    removed: int


@router.get("/packs/{pack}/seeded", response_model=list[IndustrySeededOut])
def seeded(pack: str, s: Session = DB_SESSION) -> object:
    """Everything the pack added to this business, and which of it is untouched."""
    industry.require_pack(discover(), pack)
    return [IndustrySeededOut(seeder=r.seeder, item_type=r.item_type, item_id=r.item_id, label=r.label,
                              untouched=r.untouched) for r in industry.seeded_rows(s, pack)]


@router.post("/packs/{pack}/remove-untouched", response_model=IndustryRemovedOut)
def remove_untouched(pack: str, s: Session = DB_SESSION) -> object:
    """Remove what the pack added that is still untouched and unused. Everything else stays."""
    industry.require_pack(Registry(discover()).units, pack)
    removed = industry.remove_untouched(s, pack)
    audit.record(s, "remove_untouched", "kernel.pack_seed_log", None, {"pack": pack, "removed": removed})
    return IndustryRemovedOut(removed=removed)
