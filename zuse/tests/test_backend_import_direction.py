"""§3.3 / Step B2 -- the agent must never import the API.

If zuse.agent.orchestrator can be imported in an environment where
fastapi is not installed, the dependency has not leaked. We can't
literally uninstall fastapi mid-suite, so this asserts the module's own
import list contains nothing from `backend` or `fastapi` -- the
enforceable, static version of the same check.
"""

from __future__ import annotations

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).parent.parent / "zuse" / "agent"


def _imported_top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_agent_modules_never_import_backend_or_web_framework():
    forbidden = {"backend", "fastapi", "starlette", "uvicorn"}
    offenders = []
    for path in AGENT_DIR.rglob("*.py"):
        hit = _imported_top_level_names(path) & forbidden
        if hit:
            offenders.append((str(path), hit))
    assert not offenders, f"agent modules importing the API layer: {offenders}"


def test_orchestrator_module_imports_without_web_framework_installed():
    """Weaker but real runtime check: importing the orchestrator module in
    *this* environment (which does have fastapi installed) must not
    transitively touch backend/fastapi/starlette/uvicorn."""
    import sys

    before = set(sys.modules)
    import zuse.agent.orchestrator  # noqa: F401

    after = set(sys.modules) - before
    assert not (after & {"backend", "fastapi", "starlette", "uvicorn"})
