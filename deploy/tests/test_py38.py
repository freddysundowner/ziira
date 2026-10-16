"""The installer runs on whatever python3 the server has (Ubuntu 20.04: 3.8), so its source must be 3.8-clean.

Checked three ways: every file parses as Python 3.8; a scan finds what only fails at run time on 3.8 (subscripted builtins
outside annotations, str.removeprefix/removesuffix, dict | dict, missing `from __future__ import annotations`); and, when a
python3.8 is installed, every module is really imported with it (the Docker test does that on Ubuntu 20.04 for sure).
"""
from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "installer"
FILES = sorted(ROOT.glob("*.py"))
BUILTIN_GENERICS = {"tuple", "list", "dict", "set", "frozenset", "type"}
ABC_GENERICS = {"Callable", "Iterable", "Iterator", "Mapping", "Sequence", "MutableMapping"}


def annotation_nodes(tree: ast.AST) -> set[int]:
    """ids of every node inside an annotation (these are strings thanks to the __future__ import, never evaluated)."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        anns = []
        if isinstance(node, ast.AnnAssign):
            anns.append(node.annotation)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anns += [a.annotation for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs if a.annotation]
            for extra in (node.args.vararg, node.args.kwarg):
                if extra is not None and extra.annotation is not None:
                    anns.append(extra.annotation)
            if node.returns is not None:
                anns.append(node.returns)
        for ann in anns:
            skip.update(id(n) for n in ast.walk(ann))
    return skip


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_source_is_python_38_clean(path: Path) -> None:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path), feature_version=(3, 8))
    if "__future__" not in source and path.name not in ("__init__.py", "__main__.py"):
        pytest.fail(f"{path.name}: add `from __future__ import annotations`")
    skip = annotation_nodes(tree)
    problems = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and \
                (node.value.id in BUILTIN_GENERICS or node.value.id in ABC_GENERICS) and not _imported_from_typing(tree, node.value.id):
            problems.append(f"line {node.lineno}: {node.value.id}[...] is evaluated at run time (needs Python 3.9+)")
        if isinstance(node, ast.Attribute) and node.attr in ("removeprefix", "removesuffix") and not (
                isinstance(node.value, ast.Name) and node.value.id == "util"):
            problems.append(f"line {node.lineno}: str.{node.attr} needs Python 3.9+ (use installer.util)")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr) and any(
                isinstance(side, (ast.Subscript, ast.Constant)) and not (isinstance(side, ast.Constant) and isinstance(side.value, int))
                for side in (node.left, node.right)):
            problems.append(f"line {node.lineno}: `X | Y` between types/None is evaluated at run time (needs 3.10+)")
        if isinstance(node, ast.Match if hasattr(ast, "Match") else ()):
            problems.append(f"line {node.lineno}: match statement")
    assert not problems, f"{path.name}: " + "; ".join(problems)


def _imported_from_typing(tree: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.ImportFrom) and n.module == "typing" and any(a.name == name for a in n.names) for n in ast.walk(tree))


@pytest.mark.skipif(shutil.which("python3.8") is None, reason="python3.8 not installed here (the Docker test covers it)")
def test_every_module_imports_under_a_real_python_38() -> None:
    names = [p.stem for p in FILES if p.stem != "__main__"]
    code = "import importlib,sys\nfor n in sys.argv[1:]:\n    importlib.import_module('installer.' + n)\nprint('ok')"
    out = subprocess.run(["python3.8", "-c", code, *names], cwd=ROOT.parent, capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "ok", out.stderr
