"""ORM models.

Models import SQLAlchemy, so they live here rather than in ``backend.domain``,
which the architecture test keeps free of I/O and infrastructure imports.
"""

from backend.models.identity import Manager, ManagerUserLink, User

__all__ = ["Manager", "ManagerUserLink", "User"]
