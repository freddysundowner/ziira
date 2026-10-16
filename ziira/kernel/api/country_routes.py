"""Countries for the sign-up form (public): the built-in list refined by the country packs installed here."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ziira.kernel import countries
from ziira.kernel.registry import Registry, discover

router = APIRouter(prefix="/api/v1", tags=["Countries"])


class CountryOut(BaseModel):
    code: str = Field(description="ISO 3166 two-letter code")
    name: str
    calling: str = Field(description="Phone calling code, digits only")
    currency: str = Field(description="The usual currency (ISO 4217); the business may choose another")
    zone: str = Field(description="The usual IANA time zone")
    pack: str | None = Field(description="The country pack (plugin) that names this country, if there is one")
    pack_available: bool = Field(description="That pack is installed here, so it is switched on at sign-up")
    tax_id_label: str = Field(description="What the country calls a business tax number (empty: use 'Tax number')")
    tax_id_pattern: str = Field(description="A regular expression hint for the tax number (not enforced by the server)")
    date_format: str
    number_format: str


@router.get("/countries", response_model=list[CountryOut])
def list_countries() -> object:
    """Every country a business can pick when it registers, sorted by name. No sign-in needed: the sign-up form uses it.
    Any country works even without a pack: its currency and calling code can be typed."""
    units = discover()
    try:
        installed: set[str] | None = Registry(units).installed()
    except Exception:                                   # no master database yet (a fresh checkout): show what exists
        installed = None
    return [CountryOut(**c.__dict__) for c in countries.catalogue(units, installed)]
