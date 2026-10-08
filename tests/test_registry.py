"""Install order and dependency rules (no database needed)."""

from pathlib import Path

import pytest

from ziira.kernel.errors import DependencyError
from ziira.kernel.manifest import Manifest
from ziira.kernel.registry import discover, install_order


def test_discovers_kernel_modules_and_plugin() -> None:
    units = discover()
    assert {"kernel", "products", "inventory", "pos", "finance", "people", "catalog_stats"} <= set(units)
    assert units["catalog_stats"].kind == "plugin"


def test_dependencies_come_first() -> None:
    order = install_order(discover())
    assert order[0] == "kernel"
    assert order.index("products") < order.index("inventory") < order.index("pos")
    assert order.index("payments") < order.index("pos")


def _fake(name: str, requires: tuple[str, ...]) -> Manifest:
    return Manifest(name=name, kind="module", version="1", title=name, package=name,
                    path=Path("."), requires=requires)


def test_unknown_and_circular_dependencies_rejected() -> None:
    kernel = Manifest(name="kernel", kind="module", version="1", title="k", package="k",
                      path=Path("."), core=True)
    with pytest.raises(DependencyError, match="Unknown"):
        install_order({"kernel": kernel, "a": _fake("a", ("missing",))})
    with pytest.raises(DependencyError, match="Circular"):
        install_order({"kernel": kernel, "a": _fake("a", ("b",)), "b": _fake("b", ("a",))})
