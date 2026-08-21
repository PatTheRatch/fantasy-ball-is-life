"""Structural rules, enforced rather than documented.

Charter Decision 4 asks for one reusable basketball-intelligence layer.
Documentation cannot deliver that — V1's `data_feed.py` grew to 2,699 lines
holding the ESPN client, name matching, scoreboard math, LLM prompt
construction and a CLI, and every layering statement about that codebase had
to carry an exception because of it.

So the rule is a test. A domain module that imports a database, an HTTP
client, a provider SDK or another application layer fails CI.
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
DOMAIN = REPO / "backend" / "domain"

#: Layers the domain must never reach into.
FORBIDDEN_LAYERS = ("backend.api", "backend.services", "backend.repos",
                    "backend.providers", "backend.jobs", "backend.platform")

#: Third-party packages that imply I/O or infrastructure.
FORBIDDEN_PACKAGES = (
    "sqlalchemy", "alembic", "psycopg", "asyncpg", "supabase", "postgrest",
    "requests", "httpx", "aiohttp", "urllib", "socket",
    "fastapi", "starlette", "flask",
    "espn_api", "nba_api", "anthropic", "openai",
    "boto3", "redis", "celery",
)


def _domain_modules() -> list[pathlib.Path]:
    return sorted(DOMAIN.rglob("*.py"))


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module)
    return roots


def test_domain_layer_exists() -> None:
    """Guard the guard: an empty glob would make every rule below vacuous."""
    assert len(_domain_modules()) >= 4


def test_domain_imports_no_other_application_layer() -> None:
    offences: list[str] = []
    for path in _domain_modules():
        for imported in _imported_roots(path):
            if imported.startswith(FORBIDDEN_LAYERS):
                offences.append(f"{path.relative_to(REPO)} imports {imported}")
    assert not offences, "domain must not depend on other layers:\n" + "\n".join(offences)


def test_domain_imports_no_infrastructure_package() -> None:
    offences: list[str] = []
    for path in _domain_modules():
        for imported in _imported_roots(path):
            root = imported.split(".")[0]
            if root in FORBIDDEN_PACKAGES:
                offences.append(f"{path.relative_to(REPO)} imports {imported}")
    assert not offences, "domain must stay free of I/O:\n" + "\n".join(offences)


def test_domain_has_no_module_level_side_effects() -> None:
    """No config reads, no client construction, no filesystem access at import.

    V1's `config.py` executed `load_dotenv()` and read a dozen environment
    variables at import time, which is why importing almost anything pulled in
    deployment configuration.
    """
    offences: list[str] = []
    for path in _domain_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                offences.append(f"{path.relative_to(REPO)}:{node.lineno} module-level call")
    assert not offences, "domain must not act at import time:\n" + "\n".join(offences)


def test_no_hardcoded_season_calendar() -> None:
    """Charter non-negotiable. V1 hand-typed 22 week ranges in Python and again
    in TypeScript; matchup periods are derived from the provider instead."""
    offences: list[str] = []
    for path in (REPO / "backend").rglob("*.py"):
        text = path.read_text()
        if "MATCHUP_WEEKS" in text or "_MATCHUP_WEEK_CALENDARS" in text:
            offences.append(str(path.relative_to(REPO)))
    assert not offences, "hardcoded matchup calendar found in:\n" + "\n".join(offences)


def test_routers_do_not_import_repos_models_or_sqlalchemy() -> None:
    """Business logic lives in services, not routers.

    A router that reaches for a repository, a model, or raw SQLAlchemy is doing
    business logic in the HTTP layer (charter D26 layering). Routers call into
    ``backend.services`` instead; the repo/model wiring lives in the deps layer.
    """
    routers = REPO / "backend" / "api" / "routers"
    offences: list[str] = []
    for path in sorted(routers.rglob("*.py")):
        for imported in _imported_roots(path):
            if imported.startswith(("sqlalchemy", "backend.repos", "backend.models")):
                offences.append(f"{path.relative_to(REPO)} imports {imported}")
    assert not offences, "routers must not import repos/models/sqlalchemy:\n" + "\n".join(
        offences
    )
