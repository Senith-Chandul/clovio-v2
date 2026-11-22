"""Who may do what in a project. Every project route goes through one of these."""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models import ProjectMember, Role, User


def membership(db: Session, project_id: uuid.UUID, user: User) -> ProjectMember:
    member = db.get(ProjectMember, (project_id, user.id))
    if member is None:
        # 404, not 403, so nobody can probe which projects exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return member


def require_manager(member: ProjectMember) -> ProjectMember:
    if member.role == Role.member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project's owners and managers can do that.")
    return member


def project_member(
    project_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectMember:
    return membership(db, project_id, user)


def project_manager(member: ProjectMember = Depends(project_member)) -> ProjectMember:
    return require_manager(member)
