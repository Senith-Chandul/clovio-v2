import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import project_manager, project_member
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import (
    Conversation, ConversationKind, Milestone, Notification, Project, ProjectMember, ProjectStatus, Role, Task, TaskStatus, User,
)
from app.schemas import MemberIn, MemberOut, MemberPatch, MilestoneOut, ProjectIn, ProjectOut, ProjectPatch, ProjectSummary
from app.services.tasks import update_task

router = APIRouter(prefix="/api", tags=["projects"])


def _member_out(member: ProjectMember, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id, name=user.name, email=user.email, role=member.role, skills=user.skills,
        weekly_hours=user.weekly_hours, invited=user.last_login_at is None,
    )


def _project_out(db: Session, project: Project, role: Role) -> ProjectOut:
    rows = db.execute(
        select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id).order_by(ProjectMember.joined_at)
    ).all()
    milestones = db.scalars(select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.position)).all()
    return ProjectOut(
        id=project.id, name=project.name, brief=project.brief, status=project.status, deadline=project.deadline,
        created_at=project.created_at, role=role,
        members=[_member_out(m, u) for m, u in rows],
        milestones=[MilestoneOut.model_validate(m) for m in milestones],
    )


def _set_invitee_details(user: User, body: MemberIn | MemberPatch) -> None:
    """Managers fill in name, skills and hours for people who haven't signed in; after that, it's their profile."""
    for field in ("name", "skills", "weekly_hours"):
        value = getattr(body, field)
        if value is not None:
            if user.last_login_at is not None:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"{user.name} has signed in, so they keep their own profile up to date.")
            setattr(user, field, value)


def _add_member(db: Session, project_id: uuid.UUID, body: MemberIn) -> tuple[ProjectMember, User]:
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # An invite: a user row they claim when they first sign in with this email (verified by Google or Microsoft).
        user = User(email=email, name=body.name or email.split("@")[0])
        db.add(user)
    if user.last_login_at is None:
        _set_invitee_details(user, body)
    db.flush()
    if db.get(ProjectMember, (project_id, user.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} is already in this project.")
    member = ProjectMember(project_id=project_id, user_id=user.id, role=body.role)
    db.add(member)
    db.flush()
    return member, user


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    done = func.count(Task.id).filter(Task.status == TaskStatus.done)
    rows = db.execute(
        select(Project, ProjectMember.role, func.count(Task.id), done)
        .join(ProjectMember, (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id))
        .outerjoin(Task, Task.project_id == Project.id)
        .group_by(Project.id, ProjectMember.role)
        .order_by(Project.created_at.desc())
    ).all()
    return [
        ProjectSummary(id=p.id, name=p.name, status=p.status, deadline=p.deadline, role=role, tasks_total=total, tasks_done=finished)
        for p, role, total, finished in rows
    ]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = Project(name=body.name, brief=body.brief, deadline=body.deadline, created_by=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=Role.owner))
    # Every project has one team chat; who can read it is whoever is in the project.
    db.add(Conversation(project_id=project.id, kind=ConversationKind.project))
    seen = {user.email}
    for member in body.members:
        if member.email.lower() not in seen:
            seen.add(member.email.lower())
            _add_member(db, project.id, member)
    db.commit()
    return _project_out(db, project, Role.owner)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    return _project_out(db, db.get(Project, member.project_id), member.role)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(body: ProjectPatch, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    project = db.get(Project, member.project_id)
    starting = project.status == ProjectStatus.planning and body.status == ProjectStatus.active
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field in ("name", "brief", "status"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field.capitalize()} can't be empty.")
        setattr(project, field, value)
    if starting:
        # The draft plan made no noise; now each person hears once what's theirs.
        counts = db.execute(
            select(Task.assignee_id, func.count()).where(
                Task.project_id == project.id, Task.assignee_id.is_not(None), Task.status != TaskStatus.done
            ).group_by(Task.assignee_id)
        )
        for user_id, n in counts:
            if user_id != member.user_id:
                db.add(Notification(user_id=user_id, project_id=project.id, kind="started",
                                    text=f"{project.name} has started. You have {n} task{'s' if n != 1 else ''}."))
    db.commit()
    return _project_out(db, project, member.role)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    if member.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project's owners can delete it.")
    db.delete(db.get(Project, member.project_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects/{project_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(body: MemberIn, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    if body.role == Role.owner and member.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can add another owner.")
    added, user = _add_member(db, member.project_id, body)
    db.commit()
    return _member_out(added, user)


def _owner_count(db: Session, project_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(ProjectMember.project_id == project_id, ProjectMember.role == Role.owner))


@router.patch("/projects/{project_id}/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID, body: MemberPatch, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)
):
    target = db.get(ProjectMember, (member.project_id, user_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't in this project.")
    if body.role is not None and body.role != target.role:
        if Role.owner in (body.role, target.role) and member.role != Role.owner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can make or unmake an owner.")
        if target.role == Role.owner and _owner_count(db, member.project_id) == 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "A project needs at least one owner.")
        target.role = body.role
    user = db.get(User, user_id)
    _set_invitee_details(user, body)
    db.commit()
    return _member_out(target, user)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    target = db.get(ProjectMember, (member.project_id, user_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't in this project.")
    if target.role == Role.owner and (member.role != Role.owner or _owner_count(db, member.project_id) == 1):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners can only be removed by another owner, and a project needs one.")
    # Their unfinished work goes back to the pool (through the write path, so the history shows why).
    open_tasks = db.scalars(
        select(Task).where(Task.project_id == member.project_id, Task.assignee_id == user_id, Task.status != TaskStatus.done)
    ).all()
    for task in open_tasks:
        update_task(db, task, member.user_id, {"assignee_id": None})
    db.delete(target)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
