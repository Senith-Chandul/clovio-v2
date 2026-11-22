"""The one write path for tasks. Every change (board, drawer, bulk edit, AI, voice) goes through here, so
validation and history can't drift between features. Callers commit."""

import uuid
from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    EventKind, EventSource, Milestone, Notification, Project, ProjectMember, ProjectStatus, Role, Task, TaskDependency,
    TaskEvent, TaskStatus, User, utcnow,
)
from app.schemas import TaskIn

# Fields a change may not set to null.
NOT_NULL = {"title", "description", "status", "required_skills", "position", "depends_on"}


def _plain(value):
    """A JSON-safe copy of a value for the history log."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _log(db: Session, task: Task, actor_id: uuid.UUID | None, kind: EventKind, source: EventSource, **data) -> TaskEvent:
    event = TaskEvent(project_id=task.project_id, task_id=task.id, actor_id=actor_id, kind=kind, source=source, data=data)
    db.add(event)
    return event


def _notify(db: Session, task: Task, actor_id: uuid.UUID | None, kind: str, source: EventSource, assignee_id: uuid.UUID | None = None) -> None:
    """Tell people what concerns them: a task given to them, or (for managers) a task that's blocked.
    Draft plans stay quiet; starting the project sends one summary instead (api/projects.py)."""
    project = db.get(Project, task.project_id)
    if project.status != ProjectStatus.active:
        return
    who = "Rebalancing" if source == EventSource.ai else (db.get(User, actor_id).name if actor_id else "Someone")
    if kind == "assigned":
        recipients = [assignee_id] if assignee_id else []
        text = f"{who} gave you “{task.title}” in {project.name}."
    else:
        recipients = list(db.scalars(select(ProjectMember.user_id).where(
            ProjectMember.project_id == project.id, ProjectMember.role.in_([Role.owner, Role.manager]))))
        text = f"{who} marked “{task.title}” blocked in {project.name}."
    for user_id in recipients:
        if user_id != actor_id:  # nobody is told about their own change
            db.add(Notification(user_id=user_id, project_id=project.id, task_id=task.id, kind=kind, text=text))


def _check_refs(db: Session, project_id: uuid.UUID, changes: dict) -> None:
    """A task may only point at a milestone and a person from its own project."""
    if changes.get("milestone_id") is not None:
        milestone = db.get(Milestone, changes["milestone_id"])
        if milestone is None or milestone.project_id != project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That milestone isn't in this project.")
    if changes.get("assignee_id") is not None and db.get(ProjectMember, (project_id, changes["assignee_id"])) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That person isn't a member of this project.")


def _apply_status_times(task: Task, old: TaskStatus | None, new: TaskStatus) -> None:
    # started_at and completed_at feed cycle time and the on-time rate.
    now = utcnow()
    if new == TaskStatus.in_progress and task.started_at is None:
        task.started_at = now
    if new == TaskStatus.done:
        task.completed_at = now
        task.started_at = task.started_at or now
    elif old == TaskStatus.done:
        task.completed_at = None


def set_dependencies(db: Session, task: Task, ids: list[uuid.UUID]) -> None:
    """Replace what the task waits on. Refuses tasks from other projects and loops."""
    wanted = set(ids) - {task.id}
    if wanted:
        found = set(db.scalars(select(Task.id).where(Task.id.in_(wanted), Task.project_id == task.project_id)))
        if found != wanted:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A task it waits on isn't in this project.")
        edges: dict[uuid.UUID, set[uuid.UUID]] = {}
        rows = db.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_id)
            .join(Task, Task.id == TaskDependency.task_id)
            .where(Task.project_id == task.project_id)
        )
        for task_id, depends_on_id in rows:
            edges.setdefault(task_id, set()).add(depends_on_id)
        # If any new prerequisite already waits (directly or not) on this task, linking them makes a loop.
        stack, seen = list(wanted), set()
        while stack:
            current = stack.pop()
            if current == task.id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That would make tasks wait on each other in a loop.")
            if current not in seen:
                seen.add(current)
                stack.extend(edges.get(current, ()))
    db.execute(delete(TaskDependency).where(TaskDependency.task_id == task.id))
    db.add_all(TaskDependency(task_id=task.id, depends_on_id=d) for d in wanted)
    db.flush()


def create_task(
    db: Session, project_id: uuid.UUID, actor_id: uuid.UUID | None, data: TaskIn, source: EventSource = EventSource.app
) -> Task:
    fields = data.model_dump(exclude={"id", "depends_on"})
    _check_refs(db, project_id, fields)
    if data.id is not None and db.get(Task, data.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A task with that id already exists.")
    last = db.scalar(
        select(func.max(Task.position)).where(Task.project_id == project_id, Task.milestone_id == data.milestone_id)
    )
    task = Task(
        id=data.id or uuid.uuid4(),
        project_id=project_id,
        created_by=actor_id,
        position=(last or 0) + 1,
        # A person's pick sticks; the scheduler's can be revised by a rebalance.
        assignee_locked=data.assignee_id is not None and source != EventSource.ai,
        **fields,
    )
    _apply_status_times(task, None, data.status)
    db.add(task)
    db.flush()
    if data.depends_on:
        set_dependencies(db, task, data.depends_on)
    _log(db, task, actor_id, EventKind.created, source, title=task.title)
    if task.assignee_id:
        _notify(db, task, actor_id, "assigned", source, task.assignee_id)
    return task


def update_task(
    db: Session, task: Task, actor_id: uuid.UUID | None, changes: dict, source: EventSource = EventSource.app
) -> Task:
    for field in NOT_NULL & changes.keys():
        if changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field.replace('_', ' ').capitalize()} can't be empty.")
    _check_refs(db, task.project_id, changes)
    changes = dict(changes)
    if "depends_on" in changes:
        ids = changes.pop("depends_on")
        set_dependencies(db, task, ids)
        _log(db, task, actor_id, EventKind.edited, source, fields={"depends_on": [str(i) for i in ids]})
    # The scheduler's explanation is derived, so it changes without a history entry.
    if "assignment_note" in changes:
        task.assignment_note = changes.pop("assignment_note")

    edited = {}
    for field, new in changes.items():
        old = getattr(task, field)
        if old == new:
            continue
        setattr(task, field, new)
        if field == "status":
            _apply_status_times(task, old, new)
            _log(db, task, actor_id, EventKind.status, source, **{"from": old, "to": new})
            if new == TaskStatus.blocked:
                _notify(db, task, actor_id, "blocked", source)
        elif field == "assignee_id":
            task.assignee_locked = new is not None and source != EventSource.ai
            _log(db, task, actor_id, EventKind.assigned, source, **{"from": _plain(old), "to": _plain(new)})
            _notify(db, task, actor_id, "assigned", source, new)
        else:
            edited[field] = [_plain(old), _plain(new)]
    if edited:
        _log(db, task, actor_id, EventKind.edited, source, fields=edited)
    db.flush()
    return task


def delete_task(db: Session, task: Task, actor_id: uuid.UUID | None, source: EventSource = EventSource.app) -> None:
    # The event outlives the task (its task_id becomes null), so the project history still shows the delete.
    _log(db, task, actor_id, EventKind.deleted, source, title=task.title)
    db.flush()
    db.delete(task)
    db.flush()


def add_note(db: Session, task: Task, actor_id: uuid.UUID | None, text: str, source: EventSource = EventSource.app) -> TaskEvent:
    event = _log(db, task, actor_id, EventKind.note, source, text=text)
    db.flush()
    return event
