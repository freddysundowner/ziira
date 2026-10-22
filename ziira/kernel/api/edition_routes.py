"""Editions: the list a new business chooses from (public), and the signed-in business's own edition, first steps and
switching. Switching only switches units on; it needs 'units.manage'."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import editions, industry, unit_admin
from ziira.kernel.context import RequestContext
from ziira.kernel.registry import Registry, discover
from ziira.sdk import DB_SESSION, Session, request_context, require_permission

router = APIRouter(prefix="/api/v1", tags=["Editions"])


class StepOut(BaseModel):
    id: str
    title: str
    hint: str
    to: str = Field(description="The page that does the step")
    unit: str = Field(description="The step shows only while this unit is on (empty: always)")


class EditionOut(BaseModel):
    id: str
    title: str
    pitch: str
    units: list[str] = Field(description="Units this edition switches on (what they require comes along)")
    plugin_categories: list[str] = Field(description="Plugin categories the Apps screen recommends")
    menu_groups: list[str] = Field(description="Sidebar sections in this order")
    landing: str = Field(description="Page opened after signing in; empty means Home")
    checklist: list[StepOut]
    sample_data: list[str]


class MyEditionOut(BaseModel):
    edition: EditionOut
    done: list[str] = Field(description="Ids of finished first steps")
    dismissed: bool = Field(description="The owner hid the checklist")


class SwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edition: Annotated[str, Field(max_length=30)]


class SwitchOut(BaseModel):
    enabled: list[str] = Field(description="Units newly switched on; nothing is ever switched off or deleted")
    mine: MyEditionOut


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool = True


class HideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dismissed: bool


def _out(e: editions.Edition, extra: tuple[editions.Step, ...] = ()) -> EditionOut:
    return EditionOut(id=e.id, title=e.title, pitch=e.pitch, units=list(e.units),
                      plugin_categories=list(e.plugin_categories), menu_groups=list(e.menu_groups), landing=e.landing,
                      checklist=[StepOut(id=s.id, title=s.title, hint=s.hint, to=s.to, unit=s.unit)
                                 for s in (*e.checklist, *extra)], sample_data=list(e.sample_data))


def _mine(s: Session) -> MyEditionOut:
    done, dismissed = editions.onboarding(s)
    return MyEditionOut(edition=_out(editions.get(editions.current(s)), editions.pack_checklist(s)), done=done,
                        dismissed=dismissed)


@router.get("/editions", response_model=list[EditionOut])
def list_editions() -> object:
    """The editions a new business can choose from (no sign-in needed: the sign-up form shows them)."""
    return [_out(e) for e in editions.load_editions().values()]


class IndustryChoiceOut(BaseModel):
    id: str = Field(description="The pack's name: send it as `business_type` when registering")
    title: str
    summary: str


@router.get("/industries", response_model=list[IndustryChoiceOut])
def list_industries(edition: str | None = None) -> object:
    """The kinds of service business a new business can say it is (the installed industry packs; no sign-in needed).
    `edition` narrows to the packs recommended for that edition."""
    reg = Registry(discover())
    installed = reg.installed()
    return [IndustryChoiceOut(id=m.name, title=m.title, summary=m.description)
            for m in industry.installed_packs(reg.units)
            if m.name in installed and (not edition or edition in industry.load_pack(m).editions)]


@router.get("/edition", response_model=MyEditionOut)
def my_edition(_: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """This business's edition and how far along its first steps are."""
    return _mine(s)


@router.post("/edition", response_model=SwitchOut,
             dependencies=[Depends(require_permission(unit_admin.PERMISSION))])
def switch_edition(body: SwitchIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Move to another edition. Its units are switched on; nothing already on is switched off and no data is touched."""
    newly = editions.switch(s, Registry(discover()), ctx.tenant_id, editions.resolve(body.edition))
    return SwitchOut(enabled=newly, mine=_mine(s))


@router.put("/edition/steps/{step}", response_model=MyEditionOut, status_code=status.HTTP_200_OK)
def mark_step(step: str, body: StepIn, _: RequestContext = Depends(request_context),
              s: Session = DB_SESSION) -> object:
    """Tick (or untick) a first step."""
    editions.mark_step(s, step, body.done)
    return _mine(s)


@router.put("/edition/checklist", response_model=MyEditionOut,
            dependencies=[Depends(require_permission(unit_admin.PERMISSION))])
def hide_checklist(body: HideIn, s: Session = DB_SESSION) -> object:
    """Hide or show the first-steps checklist on Home (owner)."""
    editions.dismiss(s, body.dismissed)
    return _mine(s)
