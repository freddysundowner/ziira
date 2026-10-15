"""Companies and branches: add and edit them after registration, close and reopen a branch.
Needs 'organisation.manage' (the Owner by default): tenant-wide to add a company, for the company to manage it."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import organisation
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import NotFound
from ziira.sdk import DB_SESSION, Session, request_context, require_permission

router = APIRouter(prefix="/api/v1", tags=["Organisation"],
                   dependencies=[Depends(require_permission(organisation.PERMISSION))])
Text = Annotated[str, Field(max_length=300)]


class BranchSummary(BaseModel):
    id: UUID
    code: str
    name: str
    address: str | None
    phone: str | None
    is_active: bool
    counts: dict[str, int] = Field(description="What the branch holds: users, and devices and locations when those "
                                               "units are on")


class CompanySummary(BaseModel):
    id: UUID
    name: str
    tax_id: str | None
    vat_registered: bool
    currency: str
    currency_locked: bool = Field(description="True once the company has postings: the currency can no longer change")
    country: str | None
    timezone: str
    branches: list[BranchSummary]


class CompanyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    country: Annotated[str, Field(max_length=2)] | None = None
    tax_id: Annotated[str, Field(max_length=60)] | None = None
    timezone: Annotated[str, Field(max_length=60)] | None = None
    vat_registered: bool = False
    branch_code: Annotated[str, Field(max_length=10)] | None = Field(default=None, description="First branch")
    branch_name: Text | None = None


class CompanyPatch(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    name: Text | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    country: Annotated[str, Field(max_length=2)] | None = None
    tax_id: Annotated[str, Field(max_length=60)] | None = None
    timezone: Annotated[str, Field(max_length=60)] | None = None
    vat_registered: bool | None = None


class BranchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Annotated[str, Field(max_length=10)]
    name: Text
    address: Text | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None


class BranchPatch(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    code: Annotated[str, Field(max_length=10)] | None = None
    name: Text | None = None
    address: Text | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None


@router.get("/organisation", response_model=list[CompanySummary])
def list_organisation(ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """The companies you manage with all their branches (closed ones too) and what each branch holds."""
    return organisation.list_organisation(s, ctx)


@router.post("/companies", response_model=CompanySummary, status_code=201)
def create_company(body: CompanyIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Add a company to the business (tenant-wide permission). Its books and price lists are made when first needed."""
    company_id = organisation.create_company(
        s, name=body.name, currency=body.currency, country=body.country, tax_id=body.tax_id, timezone=body.timezone,
        vat_registered=body.vat_registered, branch_code=body.branch_code, branch_name=body.branch_name)
    return organisation.one_company(s, ctx, company_id)


@router.patch("/companies/{company_id}", response_model=CompanySummary)
def update_company(company_id: UUID, body: CompanyPatch, ctx: RequestContext = Depends(request_context),
                   s: Session = DB_SESSION) -> object:
    """Change a company. The currency cannot change once the company has postings."""
    organisation.update_company(s, company_id, body.model_dump(exclude_unset=True))
    return organisation.one_company(s, ctx, company_id)


@router.post("/companies/{company_id}/branches", response_model=BranchSummary, status_code=201)
def create_branch(company_id: UUID, body: BranchIn, ctx: RequestContext = Depends(request_context),
                  s: Session = DB_SESSION) -> object:
    branch_id = organisation.create_branch(s, company_id, code=body.code, name=body.name, address=body.address,
                                           phone=body.phone)
    return _branch(s, ctx, branch_id)


@router.patch("/branches/{branch_id}", response_model=BranchSummary)
def update_branch(branch_id: UUID, body: BranchPatch, ctx: RequestContext = Depends(request_context),
                  s: Session = DB_SESSION) -> object:
    organisation.update_branch(s, branch_id, body.model_dump(exclude_unset=True))
    return _branch(s, ctx, branch_id)


@router.post("/branches/{branch_id}/deactivate", response_model=BranchSummary)
def deactivate_branch(branch_id: UUID, ctx: RequestContext = Depends(request_context),
                      s: Session = DB_SESSION) -> object:
    """Close a branch. Refused, with the reasons, while it has an open till, stock in transit or unposted documents."""
    organisation.deactivate_branch(s, branch_id)
    return _branch(s, ctx, branch_id)


@router.post("/branches/{branch_id}/reactivate", response_model=BranchSummary)
def reactivate_branch(branch_id: UUID, ctx: RequestContext = Depends(request_context),
                      s: Session = DB_SESSION) -> object:
    organisation.reactivate_branch(s, branch_id)
    return _branch(s, ctx, branch_id)


def _branch(s: Session, ctx: RequestContext, branch_id: UUID) -> object:
    for company in organisation.list_organisation(s, ctx):
        for branch in company["branches"]:
            if branch["id"] == branch_id:
                return branch
    raise NotFound("Branch not found")

