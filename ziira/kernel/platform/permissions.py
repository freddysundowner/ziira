"""What each operator role may do in the Super Admin.

Roles are a fixed, small set (owner of the platform = `superadmin`); the permissions are checked on every operator route
(`require(...)` in `ziira.kernel.api.operator_guard`). Reading anything in the console needs `platform.view`, which
every
role has; changing needs the permission of that area.
"""

from ziira.kernel.errors import Forbidden

PERMISSIONS: dict[str, str] = {
    "platform.view": "See the Super Admin: dashboard, subscribers, plans, health (no changes)",
    "platform.subscribers": "Manage subscribers: notes, trials, suspend, cancel, support sessions, delete",
    "platform.plans": "Create and change plans, prices, add-ons and coupons",
    "platform.billing": "Subscriptions, invoices, payments, plan changes and dunning",
    "platform.licences": "Issue, revoke and install licences",
    "platform.units": "Install, upgrade and uninstall units; switch a business's units",
    "platform.content": "Edit the website content",
    "platform.ai": "Manage the AI providers: keys, models, the default provider, the spend cap and quality checks",
    "platform.settings": "Platform email, registration mode and public addresses (superadmin only)",
    "platform.operators": "Add and disable operators, change roles, reset a second factor, read the action trail",
}

ROLES: dict[str, frozenset[str]] = {
    "superadmin": frozenset(PERMISSIONS),
    "billing": frozenset(
        {"platform.view", "platform.subscribers", "platform.plans", "platform.billing", "platform.licences"}
    ),
    "support": frozenset({"platform.view", "platform.subscribers"}),
    "content": frozenset({"platform.view", "platform.content"}),
    "readonly": frozenset({"platform.view"}),
}


def permissions_of(role: str) -> frozenset[str]:
    """The permissions of a role (none for an unknown one)."""
    return ROLES.get(role, frozenset())


def check(role: str, permission: str) -> None:
    """Raise Forbidden unless the role holds the permission."""
    if permission not in permissions_of(role):
        raise Forbidden(f"Your role ({role}) does not allow this: it needs '{permission}'")
