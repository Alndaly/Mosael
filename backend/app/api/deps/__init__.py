from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.permissions import get_current_user
from app.db.models import User

DbSession = Annotated[Session, Depends(session_scope)]
CurrentUser = Annotated[User, Depends(get_current_user)]

