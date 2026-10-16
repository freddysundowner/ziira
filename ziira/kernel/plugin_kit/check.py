"""`ziira plugin check PATH`: fast static checks of a plugin folder, plus a migration round trip on a scratch database.

Each check gives a finding with a code, where it was found and how to fix it. An *error* fails the check (a plugin that
breaks an architecture rule); a *warning* is something a reviewer will want to see (docs/plugin-review.md).
The rules are those in CLAUDE.md (rules 1-15) applied to one folder; `tests/test_architecture.py` and import-linter
apply the same import rules to the built-in units.
"""

import ast
import re
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ziira.kernel.manifest import SDK_VERSION, Manifest, load_manifest, sdk_compatible

PERMISSION_CALLS = {"require_permission", "require", "can", "has_anywhere", "companies_with", "scopes_with"}
NETWORK_ROOTS = (
    "httpx.",
    "requests.",
    "urllib.request.",
    "urllib3.",
    "aiohttp.",
    "socket.",
    "smtplib.",
    "ftplib.",
    "http.client.",
)
NETWORK_VERBS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "request",
    "stream",
    "urlopen",
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "SMTP",
    "SMTP_SSL",
    "FTP",
    "HTTPConnection",
    "HTTPSConnection",
}
RED_FLAG_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "os.system",
    "os.popen",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_output",
    "pickle.loads",
    "pickle.load",
    "marshal.loads",
    "ctypes.CDLL",
    "importlib.import_module",
}
SQL_REF = re.compile(
    r"\b(from|join|into|update|table|delete\s+from|truncate)\s+(\"?[a-z_][a-z0-9_]*\"?)\.(\"?[a-z_][a-z0-9_]*\"?)",
    re.IGNORECASE,
)
SQL_WRITE = re.compile(
    r"\b(insert\s+into|update|delete\s+from|truncate(?:\s+table)?|alter\s+table|drop\s+table)\s+"
    r"\"?([a-z_][a-z0-9_]*)\"?\.",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    level: str  # "error" or "warning"
    code: str
    where: str
    message: str
    fix: str = ""


@dataclass
class Report:
    plugin: str
    findings: list[Finding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, code: str, where: str, message: str, fix: str = "") -> None:
        self.findings.append(Finding(level, code, where, message, fix))

    def render(self) -> str:
        lines = [f"Checking plugin '{self.plugin}'", ""]
        for f in self.findings:
            lines.append(f"{'FAIL' if f.level == 'error' else 'WARN'}  [{f.code}] {f.where}: {f.message}")
            if f.fix:
                lines.append(f"      fix: {f.fix}")
        lines += [
            "",
            f"{len(self.errors)} error(s), {len(self.findings) - len(self.errors)} warning(s); "
            f"{len(self.checked)} checks run.",
        ]
        lines.append("RESULT: " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(lines)


# --------------------------------------------------------------------------- helpers
def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _is_test(root: Path, path: Path) -> bool:
    parts = path.relative_to(root).parts
    return "tests" in parts or path.name.startswith("test_") or path.name == "conftest.py"


def _parse(path: Path, report: Report, root: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as exc:
        report.add(
            "error",
            "syntax",
            f"{path.relative_to(root)}:{exc.lineno}",
            f"Python cannot read this file: {exc.msg}",
            "fix the syntax error",
        )
        return None


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _strip_sql(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def _known_units() -> dict[str, Manifest]:
    from ziira.kernel.registry import discover

    try:
        return discover()
    except Exception:  # noqa: BLE001 - the check must still run if some other unit is broken
        return {}


def _schema_of(name: str, units: dict[str, Manifest]) -> str:
    other = units.get(name)
    return f"plg_{name}" if other is not None and other.kind == "plugin" else name


# --------------------------------------------------------------------------- the checks
def check_plugin(path: Path, *, roundtrip: bool = True) -> Report:
    """Run every check on the plugin folder at `path`."""
    root = path.resolve()
    report = Report(root.name)
    manifest = _check_manifest(root, report)
    if manifest is None:
        return report
    units = _known_units()
    files = _python_files(root)
    trees = {f: t for f in files if (t := _parse(f, report, root)) is not None}
    _check_imports(root, manifest, trees, report)
    _check_migrations(root, manifest, units, report)
    _check_permissions(root, manifest, trees, units, report)
    _check_routes(root, trees, report)
    _check_events(root, manifest, trees, report)
    _check_money(root, trees, report)
    _check_sql_in_code(root, manifest, trees, units, report)
    _check_import_time_network(root, trees, report)
    _check_red_flags(root, trees, report)
    _check_extras(root, report)
    if roundtrip and not any(f.code.startswith("migration") for f in report.errors):
        _check_roundtrip(manifest, report)
    return report


def _check_manifest(root: Path, report: Report) -> Manifest | None:
    report.checked.append("manifest")
    file = root / "manifest.toml"
    if not file.exists():
        report.add(
            "error", "manifest", "manifest.toml", "There is no manifest.toml", "run `ziira plugin new` or add one"
        )
        return None
    try:
        raw = tomllib.loads(file.read_text())
        manifest = load_manifest(file, f"ziira_ext.{root.name}")
    except (ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            f"The manifest is not valid: {exc}",
            "compare it with docs/adding-a-module.md and a scaffolded plugin",
        )
        return None
    unit = raw.get("unit", {})
    if manifest.kind != "plugin":
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            'kind must be "plugin" (third parties build plugins)',
            'set kind = "plugin"',
        )
    if manifest.name != root.name:
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            f"name '{manifest.name}' differs from the folder '{root.name}'",
            "rename the folder or the name",
        )
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,30}", manifest.name):
        report.add(
            "error", "manifest", "manifest.toml", "name must be lower-case letters, digits and '_' (3-31 characters)"
        )
    if not re.fullmatch(r"\d+\.\d+\.\d+", manifest.version):
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            f"version '{manifest.version}' is not major.minor.patch",
            'use e.g. version = "0.1.0"',
        )
    try:
        if not sdk_compatible(manifest.sdk):
            report.add(
                "error", "manifest", "manifest.toml", f"needs SDK {manifest.sdk}, this platform has {SDK_VERSION}"
            )
    except ValueError as exc:
        report.add("error", "manifest", "manifest.toml", str(exc))
    if not manifest.category:
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            "category is missing",
            'add category = "..." (see manifest.py CATEGORIES)',
        )
    for key in ("title", "description"):
        if not unit.get(key):
            report.add("warning", "manifest", "manifest.toml", f"{key} is empty", f"add a plain one-sentence {key}")
    if not manifest.publisher:
        report.add("warning", "manifest", "manifest.toml", "publisher is empty", "say who made the plugin")
    if manifest.api_prefix and not manifest.api_prefix.startswith("/api/v1/plugins/"):
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            f"api_prefix '{manifest.api_prefix}' must start with /api/v1/plugins/",
            f'use api_prefix = "/api/v1/plugins/{manifest.name.replace("_", "-")}"',
        )
    if (root / "api" / "routes.py").exists() and not manifest.api_prefix:
        report.add(
            "error",
            "manifest",
            "manifest.toml",
            "api/routes.py exists but the manifest has no api_prefix",
            "add api_prefix under [provides]",
        )
    for code in manifest.permissions:
        if not code.startswith(manifest.name + "."):
            report.add(
                "error",
                "permissions",
                "manifest.toml",
                f"permission '{code}' must start with '{manifest.name}.'",
                f"rename it to {manifest.name}.<action>",
            )
    return manifest


def _check_imports(root: Path, m: Manifest, trees: dict[Path, ast.Module], report: Report) -> None:
    report.checked.append("imports")
    for file, tree in trees.items():
        rel = file.relative_to(root)
        for node in ast.walk(tree):
            names: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                names = [(a.name, node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(rel.parts):  # climbs out of the plugin
                        report.add(
                            "error",
                            "import",
                            f"{rel}:{node.lineno}",
                            "A relative import leaves the plugin folder",
                            "import from ziira.sdk instead",
                        )
                    continue
                if node.module:
                    names = [(node.module, node.lineno)]
            for name, line in names:
                parts = name.split(".")
                where = f"{rel}:{line}"
                if parts[0] != "ziira" and parts[0] != "ziira_ext":
                    continue
                if parts[0] == "ziira" and len(parts) >= 2 and parts[1] == "kernel":
                    report.add(
                        "error",
                        "import",
                        where,
                        f"imports {name}: plugins may not import the kernel",
                        "import from ziira.sdk (it exposes what plugins may use)",
                    )
                elif parts[0] == "ziira" and len(parts) >= 2 and parts[1] == "sdk":
                    continue
                elif parts[0] == "ziira" and len(parts) >= 3 and parts[1] in ("modules", "plugins"):
                    if parts[2] != m.name and (len(parts) < 4 or parts[3] != "public"):
                        report.add(
                            "error",
                            "import",
                            where,
                            f"imports {name}: another unit's internals",
                            f"import ziira.{parts[1]}.{parts[2]}.public instead, and list the unit under "
                            "requires/optional",
                        )
                elif parts[0] == "ziira_ext" and len(parts) >= 2:
                    if parts[1] != m.name and (len(parts) < 3 or parts[2] != "public"):
                        report.add(
                            "error",
                            "import",
                            where,
                            f"imports {name}: another plugin's internals",
                            f"import ziira_ext.{parts[1]}.public instead",
                        )
                else:
                    report.add(
                        "error",
                        "import",
                        where,
                        f"imports {name}: not part of the SDK",
                        "plugins may import ziira.sdk, their own package and other units' public.py only",
                    )


def _check_migrations(root: Path, m: Manifest, units: dict[str, Manifest], report: Report) -> None:
    report.checked.append("migrations")
    folder = root / "migrations"
    ups = sorted(folder.glob("*.up.sql")) if folder.exists() else []
    if not ups:
        report.add(
            "error",
            "migration",
            "migrations/",
            "There is no migrations/NNNN_name.up.sql",
            "a plugin that stores data needs 0001_init.up.sql and 0001_init.down.sql",
        )
        return
    schema = f"plg_{m.name}"
    allowed = {schema, "kernel", *(_schema_of(r, units) for r in m.requires)}
    for up in ups:
        rel = f"migrations/{up.name}"
        down = folder / up.name.replace(".up.sql", ".down.sql")
        if not re.fullmatch(r"\d{4}_[a-z0-9_]+\.up\.sql", up.name):
            report.add("error", "migration", rel, "Name migrations NNNN_name.up.sql (four digits)")
        if not down.exists():
            report.add(
                "error",
                "migration-down",
                rel,
                "There is no matching .down.sql",
                f"add {down.name} that undoes it (drop schema {schema} cascade for the first one)",
            )
        sql = _strip_sql(up.read_text()).lower()
        for found in re.finditer(r"create\s+schema\s+(?:if\s+not\s+exists\s+)?\"?([a-z0-9_]+)\"?", sql):
            if found.group(1) != schema:
                report.add("error", "migration", rel, f"creates schema '{found.group(1)}'", f"use only {schema}")
        for found in re.finditer(r"references\s+(\"?[a-z0-9_]+\"?)(\.?)", sql):
            target = found.group(1).strip('"')
            if not found.group(2):
                report.add(
                    "error",
                    "migration-fk",
                    rel,
                    f"a foreign key to '{target}' names no schema",
                    f"write references {schema}.{target}(id) or references kernel.<table>(id)",
                )
            elif target not in allowed:
                report.add(
                    "error",
                    "migration-fk",
                    rel,
                    f"a foreign key into schema '{target}', which is not the kernel, this plugin or a required unit",
                    "make it a plain uuid column (a soft reference), or add the unit to requires",
                )
        for table in re.finditer(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z0-9_\"]+)\.([a-z0-9_\"]+)\s*\(", sql):
            tschema, tname = table.group(1).strip('"'), table.group(2).strip('"')
            full = f"{tschema}.{tname}"
            if tschema != schema:
                report.add(
                    "error", "migration", rel, f"creates table {full} outside {schema}", f"create it in {schema}"
                )
                continue
            body = _balanced(sql, table.end() - 1)
            if not re.search(r"\btenant_id\b", body):
                report.add(
                    "error",
                    "migration-rls",
                    rel,
                    f"table {full} has no tenant_id column",
                    "add tenant_id uuid not null references kernel.tenant(id)",
                )
            for need, phrase in (
                ("enable", rf"alter\s+table\s+{re.escape(full)}\s+enable\s+row\s+level\s+security"),
                ("force", rf"alter\s+table\s+{re.escape(full)}\s+force\s+row\s+level\s+security"),
                ("policy", rf"create\s+policy\s+\w+\s+on\s+{re.escape(full)}\b"),
            ):
                if not re.search(phrase, sql):
                    what = {
                        "enable": "enables row-level security",
                        "force": "forces row-level security",
                        "policy": "has a policy",
                    }[need]
                    report.add(
                        "error",
                        "migration-rls",
                        rel,
                        f"table {full} never {what}",
                        f"add: alter table {full} enable row level security; alter table {full} force row level "
                        f"security; create policy tenant_isolation on {full} "
                        "using (tenant_id = kernel.current_tenant()) "
                        "with check (tenant_id = kernel.current_tenant());",
                    )
        if re.search(r"\b(double\s+precision|real|float[48]?|money)\b", sql):
            report.add(
                "error",
                "money",
                rel,
                "uses a floating-point or money column type",
                "use numeric(18,2) for amounts and numeric(18,4) for quantities",
            )
        for stmt in re.finditer(r"\b(?:alter|drop)\s+(?:table|schema)\s+(?:if\s+exists\s+)?\"?([a-z0-9_]+)\"?", sql):
            if stmt.group(1) not in (schema, "plg_" + m.name):
                report.add("error", "migration", rel, f"changes '{stmt.group(1)}', which this plugin does not own")
    for down in sorted(folder.glob("*.down.sql")):
        if not (folder / down.name.replace(".down.sql", ".up.sql")).exists():
            report.add("error", "migration-down", f"migrations/{down.name}", "has no matching .up.sql")
    first_down = folder / "0001_init.down.sql"
    if first_down.exists() and schema not in first_down.read_text().lower():
        report.add(
            "warning",
            "migration-down",
            "migrations/0001_init.down.sql",
            f"does not drop schema {schema}",
            f"add: drop schema if exists {schema} cascade;",
        )


def _balanced(sql: str, open_at: int) -> str:
    depth = 0
    for i in range(open_at, len(sql)):
        depth += {"(": 1, ")": -1}.get(sql[i], 0)
        if depth == 0:
            return sql[open_at : i + 1]
    return sql[open_at:]


def _permission_uses(tree: ast.Module) -> list[tuple[str, int]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if (
                name in PERMISSION_CALLS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.append((node.args[0].value, node.lineno))
    return found


def _check_permissions(
    root: Path, m: Manifest, trees: dict[Path, ast.Module], units: dict[str, Manifest], report: Report
) -> None:
    report.checked.append("permissions")
    others = {code for name, u in units.items() if name != m.name for code in u.permissions}
    used: set[str] = set()
    for file, tree in trees.items():
        if _is_test(root, file):
            continue
        for code, line in _permission_uses(tree):
            used.add(code)
            if code not in m.permissions and code not in others:
                report.add(
                    "error",
                    "permissions",
                    f"{file.relative_to(root)}:{line}",
                    f"uses permission '{code}', which no unit declares",
                    f'declare it under [permissions] in manifest.toml as "{code}" = "what it allows"',
                )
    for code in sorted(set(m.permissions) - used):
        report.add(
            "warning",
            "permissions",
            "manifest.toml",
            f"permission '{code}' is declared but never checked in code",
            "remove it, or check it with require_permission / current_context().require",
        )


def _mentions_permission(node: ast.AST, guards: set[str] | None = None) -> bool:
    """True if the code calls require_permission or names a module-level guard built from it (VIEW = [...])."""
    return any(
        (isinstance(n, ast.Call) and _dotted(n.func).split(".")[-1] == "require_permission")
        or (isinstance(n, ast.Name) and n.id in (guards or set()))
        for n in ast.walk(node)
    )


def _module_guards(tree: ast.Module) -> set[str]:
    """Names assigned at module level to something that calls require_permission (a shared `VIEW = [Depends(...)]`)."""
    return {
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign) and _mentions_permission(node.value)
        for t in node.targets
        if isinstance(t, ast.Name)
    }


def _check_routes(root: Path, trees: dict[Path, ast.Module], report: Report) -> None:
    report.checked.append("endpoints")
    for file, tree in trees.items():
        if _is_test(root, file) or file.name not in ("routes.py",) and "api" not in file.relative_to(root).parts:
            continue
        rel = file.relative_to(root)
        router_guarded: dict[str, bool] = {}
        guards = _module_guards(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _dotted(node.value.func).split(".")[-1] == "APIRouter"
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        router_guarded[target.id] = any(
                            k.arg == "dependencies" and _mentions_permission(k.value, guards)
                            for k in node.value.keywords
                        )
                        if target.id == "public_router":
                            report.add(
                                "warning",
                                "endpoints",
                                f"{rel}:{node.lineno}",
                                "public_router serves endpoints without sign-in",
                                "it must authenticate callers itself (a signature); reviewers will look at it",
                            )
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for deco in fn.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in ("get", "post", "put", "patch", "delete")
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id in router_guarded
                ):
                    if router_guarded[deco.func.value.id] or deco.func.value.id == "public_router":
                        continue
                    guarded = _mentions_permission(deco, guards) or any(
                        _mentions_permission(d, guards) for d in [*fn.args.defaults, *fn.args.kw_defaults] if d
                    )
                    if not guarded:
                        report.add(
                            "error",
                            "endpoints",
                            f"{rel}:{fn.lineno}",
                            f"endpoint {fn.name} ({deco.func.attr.upper()}) has no require_permission",
                            'add dependencies=[Depends(require_permission("<plugin>.<action>"))]',
                        )


def _event_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    published: set[str] = set()
    subscribed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func).split(".")[-1]
            if name == "Event":
                args = [*node.args[:1], *(k.value for k in node.keywords if k.arg == "type")]
                published |= {a.value for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
            elif name in ("subscribe", "subscribe_after") and node.args and isinstance(node.args[0], ast.Constant):
                subscribed.add(str(node.args[0].value))
    return published, subscribed


def _check_events(root: Path, m: Manifest, trees: dict[Path, ast.Module], report: Report) -> None:
    report.checked.append("events")
    constants: dict[str, str] = {}
    for tree in trees.values():
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        constants[t.id] = node.value.value
    published: set[str] = set()
    subscribed: set[str] = set()
    for file, tree in trees.items():
        if _is_test(root, file):
            continue
        for call in ast.walk(tree):
            if (
                isinstance(call, ast.Call)
                and _dotted(call.func).split(".")[-1] == "Event"
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id in constants
            ):
                published.add(constants[call.args[0].id])
        p, s = _event_names(tree)
        published |= p
        subscribed |= s
    for event in sorted(published - set(m.publishes)):
        report.add(
            "error",
            "events",
            "manifest.toml",
            f"publishes '{event}' but the manifest does not declare it",
            f'add "{event}" to publishes under [provides]',
        )
    for event in sorted(set(m.publishes) - published):
        report.add("warning", "events", "manifest.toml", f"declares publishing '{event}' but no code publishes it")
    for event in sorted(subscribed - set(m.subscribes)):
        report.add(
            "warning",
            "events",
            "manifest.toml",
            f"subscribes to '{event}' but the manifest does not declare it",
            f'add "{event}" to subscribes under [provides]',
        )


MONEY_WORDS = re.compile(
    r"(?<![a-z])(?:amount|price|cost|total|tax|vat|balance|money|quantity|qty|rate|fee|salary|wage|pay|payment|discount"
    r"|net|gross|debit|credit|charge|refund|invoice|bill|stock)s?(?![a-z])",
    re.IGNORECASE,
)


def _check_money(root: Path, trees: dict[Path, ast.Module], report: Report) -> None:
    """`float` next to a money-like name is an error; a float elsewhere (a timeout in seconds) is only a warning."""
    report.checked.append("money")
    for file, tree in trees.items():
        if _is_test(root, file):
            continue
        rel = file.relative_to(root)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            flagged = (isinstance(node, ast.Name) and node.id == "float" and isinstance(node.ctx, ast.Load)) or (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.fullmatch(r"\s*float\s*", node.value)
            )
            if not flagged:
                continue
            context = _float_context(node, parents)
            money_like = bool(MONEY_WORDS.search(context))
            report.add(
                "error" if money_like else "warning",
                "money",
                f"{rel}:{getattr(node, 'lineno', 0)}",
                f"uses float near '{context[:60]}'"
                + (", which must never hold money or quantities" if money_like else ""),
                "use Decimal (ziira.sdk: Amount, Quantity, Rate, UnitCost, money())"
                if money_like
                else "fine for things that are not money or quantities (a timeout); never for amounts",
            )


def _float_context(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """The code a `float` sits in, as short text: the argument, variable or function it types, or its call."""
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.arg):
            return current.arg
        if isinstance(current, ast.AnnAssign | ast.Assign | ast.Call | ast.Return | ast.keyword):
            return ast.unparse(current)[:120]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current.name
        current = parents.get(current)
    return ""


def _check_sql_in_code(
    root: Path, m: Manifest, trees: dict[Path, ast.Module], units: dict[str, Manifest], report: Report
) -> None:
    report.checked.append("sql")
    schemas = {m_.name if m_.kind == "module" else f"plg_{m_.name}" for m_ in units.values() if not m_.core}
    schemas.discard(f"plg_{m.name}")
    schemas |= {"master", "pg_catalog", "information_schema"}
    for file, tree in trees.items():
        if _is_test(root, file):
            continue
        rel = file.relative_to(root)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 8):
                continue
            sql = node.value
            for found in SQL_REF.finditer(sql):
                schema = found.group(2).strip('"').lower()
                if schema in schemas:
                    report.add(
                        "error",
                        "sql",
                        f"{rel}:{node.lineno}",
                        f"raw SQL on schema '{schema}', which is not this plugin's",
                        "use the owning unit's public.py, or listen to its events",
                    )
            for found in SQL_WRITE.finditer(sql):
                if found.group(2).lower() == "kernel":
                    report.add(
                        "error",
                        "sql",
                        f"{rel}:{node.lineno}",
                        "raw SQL writes a kernel table",
                        "use ziira.sdk services (audit_record, flag_for_review, send_notification, ...)",
                    )


def _is_network_call(call: ast.Call) -> bool:
    name = _dotted(call.func)
    return any(name.startswith(root_) for root_ in NETWORK_ROOTS) and name.split(".")[-1] in NETWORK_VERBS


def _module_level_calls(body: list[ast.stmt]) -> list[ast.Call]:
    """Calls that run when the module is imported: not inside functions or lambdas (class bodies do run)."""
    found: list[ast.Call] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            for deco in getattr(node, "decorator_list", []):
                visit(deco)
            for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d]]:
                visit(default)
            return
        if isinstance(node, ast.Call):
            found.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in body:
        visit(stmt)
    return found


def _check_import_time_network(root: Path, trees: dict[Path, ast.Module], report: Report) -> None:
    report.checked.append("network-at-import")
    for file, tree in trees.items():
        if _is_test(root, file):
            continue
        for call in _module_level_calls(tree.body):
            if _is_network_call(call):
                report.add(
                    "error",
                    "network-at-import",
                    f"{file.relative_to(root)}:{call.lineno}",
                    f"calls {_dotted(call.func)} when the module is imported",
                    "make network calls inside functions that run on a request or a job, never at import",
                )


def _check_red_flags(root: Path, trees: dict[Path, ast.Module], report: Report) -> None:
    report.checked.append("review-flags")
    for file, tree in trees.items():
        if _is_test(root, file):
            continue
        rel = file.relative_to(root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _dotted(node.func) in RED_FLAG_CALLS:
                report.add(
                    "warning",
                    "review",
                    f"{rel}:{node.lineno}",
                    f"calls {_dotted(node.func)}",
                    "reviewers will ask why; avoid it if you can",
                )
            elif isinstance(node, ast.Attribute) and _dotted(node) in ("os.environ", "os.getenv"):
                report.add(
                    "warning",
                    "review",
                    f"{rel}:{node.lineno}",
                    "reads environment variables",
                    "keep a plugin's settings in company settings or stored credentials, not the environment",
                )
            elif isinstance(node, ast.Call) and _is_network_call(node):
                report.add(
                    "warning",
                    "review",
                    f"{rel}:{node.lineno}",
                    f"makes a network call ({_dotted(node.func)}): list the hosts in the README",
                    "reviewers check what leaves the system (docs/plugin-review.md)",
                )


def _check_extras(root: Path, report: Report) -> None:
    report.checked.append("extras")
    if not (root / "README.md").exists():
        report.add(
            "warning", "extras", "README.md", "There is no README", "say what the plugin does and what it sends where"
        )
    tests = root / "tests"
    if not tests.exists() or not list(tests.glob("test_*.py")):
        report.add("warning", "extras", "tests/", "There are no tests", "add tests with the kit in ziira.sdk.testing")


def _check_roundtrip(m: Manifest, report: Report) -> None:
    """Apply the migrations to a scratch copy of the template, check the tables, undo them, apply them again."""
    report.checked.append("migration-roundtrip")
    from sqlalchemy import create_engine, make_url, text

    from ziira.kernel.config import get_settings
    from ziira.kernel.db import server_engine
    from ziira.kernel.registry import _run_script, apply_migrations, migration_files

    settings = get_settings()
    name = f"ziira_check_{uuid.uuid4().hex[:10]}"
    schema = f"plg_{m.name}"
    try:
        with server_engine().connect() as conn:
            conn.exec_driver_sql(f'create database "{name}" template "{settings.template_database}"')
    except Exception as exc:  # noqa: BLE001 - no database to try on is not the plugin's fault
        report.add(
            "warning",
            "migration-roundtrip",
            "migrations/",
            "skipped: no scratch database "
            f"({type(exc).__name__}: {str(exc).splitlines()[0][:120] if str(exc) else ''})",
            "start the database (make db-up) and install the platform (ziira install --all)",
        )
        return
    engine = create_engine(make_url(settings.tenant_server_url).set(database=name))
    try:

        def tables(conn: Any) -> dict[str, bool]:
            rows = conn.execute(
                text(
                    "select c.relname, c.relforcerowsecurity, "
                    "exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'tenant_id' "
                    "        and not a.attisdropped) as has_tenant "
                    "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = :s and c.relkind = 'r'"
                ),
                {"s": schema},
            )
            for r in rows.all():
                if not (r.relforcerowsecurity and r.has_tenant):
                    report.add(
                        "error",
                        "migration-rls",
                        f"table {schema}.{r.relname}",
                        "after migrating, the table lacks tenant_id or forced row-level security",
                    )
            return {
                r.relname: True
                for r in conn.execute(
                    text(
                        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = :s and c.relkind = 'r'"
                    ),
                    {"s": schema},
                )
            }

        with engine.begin() as conn:
            apply_migrations(conn, m)
            first = tables(conn)
        with engine.begin() as conn:
            for f in migration_files(m, "down"):
                _run_script(conn, f.read_text())
            left = conn.execute(
                text("select count(*) from pg_namespace where nspname = :s"), {"s": schema}
            ).scalar_one()
        if left:
            report.add(
                "error",
                "migration-down",
                "migrations/",
                f"after the down migrations schema {schema} still exists",
                f"make 0001_init.down.sql end with: drop schema if exists {schema} cascade;",
            )
            return
        with engine.begin() as conn:
            for f in migration_files(m, "up"):
                _run_script(conn, f.read_text())
            if tables(conn) != first:
                report.add(
                    "error", "migration-roundtrip", "migrations/", "applying the migrations again gave different tables"
                )
    except Exception as exc:  # noqa: BLE001 - a migration that fails to run is a finding
        report.add(
            "error",
            "migration-roundtrip",
            "migrations/",
            f"the migrations do not run cleanly: {str(exc).splitlines()[0][:200]}",
            "run them by hand with psql to see the error",
        )
    finally:
        engine.dispose()
        with server_engine().connect() as conn:
            conn.exec_driver_sql(f'drop database if exists "{name}" with (force)')
