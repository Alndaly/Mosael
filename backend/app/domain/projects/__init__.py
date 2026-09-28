"""项目领域:项目行只在这里建(归属见 app/domain/ownership.py)。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Project


def create_project(db: Session, workspace_id: str, name: str) -> Project:
    """在工作区里建一个项目(flush 拿到 id,提交交给调用方)。"""
    project = Project(workspace_id=workspace_id, name=name)
    db.add(project)
    db.flush()
    return project
