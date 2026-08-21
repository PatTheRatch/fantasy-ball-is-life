"""Identity endpoints: the authenticated user's own record."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import UserDTO, get_current_user
from backend.api.policy import RoutePolicy, declare_policy

router = APIRouter(prefix="/api/v1")


@router.get("/me")
@declare_policy(RoutePolicy.AUTHENTICATED)
def me(user: UserDTO = Depends(get_current_user)) -> UserDTO:
    return user
