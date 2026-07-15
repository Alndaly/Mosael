from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.db import session_scope

DbSession = Annotated[Session, Depends(session_scope)]

