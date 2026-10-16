"""`ziira plugin new`: write a complete, working plugin that passes `ziira plugin check`."""

import re
from pathlib import Path

from ziira.kernel.manifest import CATEGORIES

NAME = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
ZIIRA_ROOT = Path(__file__).resolve().parent.parent.parent


def package_for(dest_root: Path) -> str:
    """The Python package a plugin in this folder is imported as."""
    return "ziira.plugins" if dest_root.resolve() == (ZIIRA_ROOT / "plugins").resolve() else "ziira_ext"


def new_plugin(name: str, category: str, countries: list[str], dest_root: Path | None = None) -> Path:
    """Create the plugin folder and return it."""
    if not NAME.match(name):
        raise ValueError(
            "A plugin name is 3 to 31 characters: lower-case letters, digits and '_', starting with a letter"
        )
    if category not in CATEGORIES:
        raise ValueError(f"The category must be one of: {', '.join(CATEGORIES)}")
    if any(not re.fullmatch(r"[A-Z]{2}", c) for c in countries):
        raise ValueError("Countries are two-letter codes such as KE")
    root = dest_root or ZIIRA_ROOT / "plugins"
    folder = root / name
    if folder.exists():
        raise ValueError(f"{folder} already exists")
    values = {
        "name": name,
        "title": name.replace("_", " ").title(),
        "category": category,
        "slug": name.replace("_", "-"),
        "package": f"{package_for(root)}.{name}",
        "countries": f"countries = [{', '.join(repr(c).replace(chr(39), chr(34)) for c in countries)}]\n"
        if countries
        else "",
    }
    for relative, template in TEMPLATES.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_fill(template, values))
    return folder


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


TEMPLATES: dict[str, str] = {
    "manifest.toml": """[unit]
name = "{{name}}"
title = "{{title}}"
description = "One plain sentence for the Apps & plugins screen."
category = "{{category}}"
{{countries}}kind = "plugin"
version = "0.1.0"
sdk = ">=1.0,<2.0"
publisher = "Your name or company"
homepage = ""
requires = []

[provides]
api_prefix = "/api/v1/plugins/{{slug}}"
publishes = ["{{name}}.item_created"]

[permissions]
"{{name}}.view" = "See the items"
"{{name}}.manage" = "Add items"

# The Owner role always receives every permission. Say which other default roles get which.
[roles]
"Branch Manager" = ["{{name}}.view", "{{name}}.manage"]
"Accountant" = ["{{name}}.view"]
""",
    "__init__.py": '"""{{title}}."""\n',
    "README.md": """# {{title}}

What this plugin does, in two sentences.

- Own schema `plg_{{name}}` (created and removed by its migrations); every table has `tenant_id` and forced
  row-level security.
- API under `/api/v1/plugins/{{slug}}`: `GET /items` (`{{name}}.view`), `POST /items` (`{{name}}.manage`).
- Publishes `{{name}}.item_created`.

```bash
ziira plugin check .          # static checks: run before every commit
ziira plugin test .           # this plugin's tests
ziira plugin pack .           # a distributable archive with a checksum
```

See docs/writing-a-plugin.md and docs/plugin-review.md.
""",
    "migrations/0001_init.up.sql": """create schema if not exists plg_{{name}};

create table plg_{{name}}.item (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references kernel.tenant(id),
  company_id uuid not null references kernel.company(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  name       text not null,
  quantity   numeric(18,4) not null default 0
);
alter table plg_{{name}}.item enable row level security;
alter table plg_{{name}}.item force row level security;
create policy tenant_isolation on plg_{{name}}.item
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
""",
    "migrations/0001_init.down.sql": "drop schema if exists plg_{{name}} cascade;\n",
    "hooks.py": '''"""How this plugin plugs into other units' sockets (declare each under [extends] in manifest.toml).

Nothing is plugged in yet. Two examples, to copy when you need them (an owner unit must be in `requires`/`optional`):

    from ziira.sdk import Session, ValidationFailed, provides, validate

    # Block an action another unit offers a hook for:
    @validate("products.product.before_create")
    def refuse_odd_names(session: Session, draft) -> None:
        if "!" in draft.name:
            raise ValidationFailed("Product names cannot contain '!'")

    # Supply something another unit asks for (a socket's contract class comes from that unit's public.py):
    @provides("kernel.integrity_check")
    class MyCheck(IntegrityCheck): ...

See docs/extending-units.md.
"""
''',
    "public.py": '''"""The only file other units may import from this plugin."""

ITEM_CREATED = "{{name}}.item_created"
''',
    "api/__init__.py": "",
    "api/schemas.py": '''"""Request and response shapes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Quantity


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)
    quantity: Quantity = Field(default=0)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    name: str
    quantity: Quantity
    created_at: datetime
''',
    "api/routes.py": '''"""HTTP only: check the permission, call a service, return its answer."""

from uuid import UUID

from fastapi import APIRouter, Depends

from ziira.sdk import DB_SESSION, Session, current_context, page_limit, page_offset, require_permission

from ..repository import items_repo
from ..services import create_item
from . import schemas

router = APIRouter()


@router.get("/items", response_model=list[schemas.ItemOut], dependencies=[Depends(require_permission("{{name}}.view"))])
def list_items(limit: int = page_limit(), offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    """Items of the companies the caller may see."""
    return items_repo.list_items(session, current_context().companies_with("{{name}}.view"), limit, offset)


@router.get("/items/{item_id}", response_model=schemas.ItemOut,
            dependencies=[Depends(require_permission("{{name}}.view"))])
def get_item(item_id: UUID, session: Session = DB_SESSION) -> object:
    return items_repo.get_item(session, item_id)


@router.post("/items", response_model=schemas.ItemOut, status_code=201,
             dependencies=[Depends(require_permission("{{name}}.manage"))])
def add_item(body: schemas.ItemIn, session: Session = DB_SESSION) -> object:
    return create_item.create_item(session, company_id=body.company_id, name=body.name, quantity=body.quantity)
''',
    "services/__init__.py": "",
    "services/create_item.py": '''"""Use case: add an item. Validate (domain), save (repository), audit, publish."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.sdk import Event, Session, audit_record, check_company, current_context, publish

from ..domain import rules
from ..public import ITEM_CREATED
from ..repository import items_repo


def create_item(session: Session, *, company_id: UUID, name: str, quantity: Decimal) -> Any:
    """Add an item to a company the caller may manage."""
    current_context().require("{{name}}.manage", company_id=company_id)
    check_company(session, company_id)
    clean = rules.clean_name(name)
    item = items_repo.insert_item(session, company_id=company_id, name=clean, quantity=quantity)
    audit_record(session, "create", "plg_{{name}}.item", item.id, {"name": clean})
    publish(session, Event(ITEM_CREATED, "plg_{{name}}.item", item.id, {"company_id": company_id, "name": clean}))
    return item
''',
    "domain/__init__.py": "",
    "domain/rules.py": '''"""Pure business rules: no database, no HTTP. Easy to test."""

from ziira.sdk import ValidationFailed


def clean_name(name: str) -> str:
    """Trim an item name; it must not be empty."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValidationFailed("An item needs a name")
    return cleaned
''',
    "repository/__init__.py": "",
    "repository/items_repo.py": '''"""Database access for this plugin's schema only."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import NotFound, Session, current_context

COLUMNS = "id, company_id, name, quantity, created_at"


def insert_item(session: Session, *, company_id: UUID, name: str, quantity: Decimal) -> Any:
    ctx = current_context()
    return session.execute(text(
        "insert into plg_{{name}}.item (tenant_id, company_id, created_by, name, quantity) "
        f"values (kernel.current_tenant(), :c, :u, :n, :q) returning {COLUMNS}"),
        {"c": str(company_id), "u": str(ctx.user_id) if ctx.user_id else None, "n": name, "q": quantity}).one()


def get_item(session: Session, item_id: UUID) -> Any:
    row = session.execute(text(f"select {COLUMNS} from plg_{{name}}.item where id = :i"), {"i": str(item_id)}).first()
    if row is None:
        raise NotFound("Item not found")
    current_context().require("{{name}}.view", company_id=row.company_id)
    return row


def list_items(session: Session, companies: set[UUID] | None, limit: int, offset: int) -> list[Any]:
    """`companies` is None for all, else the companies the caller may see."""
    if companies is not None and not companies:
        return []
    scope = "" if companies is None else "where company_id = any(:cs)"
    return list(session.execute(text(
        f"select {COLUMNS} from plg_{{name}}.item {scope} order by created_at desc limit :l offset :o"),
        {"cs": [str(c) for c in companies or []], "l": limit, "o": offset}))
''',
    "tests/__init__.py": "",
    "tests/conftest.py": '''"""Fixtures from the testing kit: `registry` (a throw-away platform) and `client`."""

from ziira.sdk.testing import client, registry  # noqa: F401
''',
    "tests/test_domain.py": """import pytest

from {{package}}.domain.rules import clean_name
from ziira.sdk import ValidationFailed


def test_names_are_trimmed() -> None:
    assert clean_name("  Blue   widget ") == "Blue widget"


def test_an_empty_name_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        clean_name("   ")
""",
    "tests/test_api.py": '''"""The API end to end, with the checks every plugin should pass."""

from ziira.sdk.testing import (
    assert_all_routes_guarded,
    assert_tenant_isolation,
    make_tenant,
    run_outbox_once,
    sign_in,
    user_with_role,
)

BASE = "/api/v1/plugins/{{slug}}"


def test_add_and_list_items(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_tenant("Scaffold Shop", units=["{{name}}"])
    owner = sign_in(client, shop)
    made = client.post(f"{BASE}/items", headers=owner.headers,
                       json={"company_id": str(shop.company_id), "name": " Blue  widget ", "quantity": "2.5"})
    assert made.status_code == 201, made.text
    assert made.json()["name"] == "Blue widget" and made.json()["quantity"] == "2.5000"
    assert [i["id"] for i in client.get(f"{BASE}/items", headers=owner.headers).json()] == [made.json()["id"]]
    run_outbox_once()                                   # events reach after-commit handlers


def test_only_people_with_the_permission_may_add(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_tenant("Scaffold Perms", units=["{{name}}"])
    viewer = user_with_role(client, shop, permissions=["{{name}}.view"])
    body = {"company_id": str(shop.company_id), "name": "x"}
    assert client.post(f"{BASE}/items", headers=viewer.headers, json=body).status_code == 403
    assert client.get(f"{BASE}/items", headers=viewer.headers).status_code == 200


def test_every_route_is_guarded(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_tenant("Scaffold Guard", units=["{{name}}"])
    assert assert_all_routes_guarded(client.app, BASE, client=client, tenant=shop) >= 3


def test_another_business_cannot_see_the_items(client, registry) -> None:  # type: ignore[no-untyped-def]
    one, two = make_tenant("Scaffold One", units=["{{name}}"]), make_tenant("Scaffold Two", units=["{{name}}"])
    made = client.post(f"{BASE}/items", headers=sign_in(client, one).headers,
                       json={"company_id": str(one.company_id), "name": "Secret"}).json()
    assert_tenant_isolation(client, sign_in(client, two), f"{BASE}/items/{made['id']}", list_path=f"{BASE}/items",
                            record_id=made["id"])
''',
}
