import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import membership, project_manager, project_member, require_manager
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import EventSource, Milestone, Project, ProjectMember, ProjectStatus, Task, TaskEvent, TaskStatus, User
from app.schemas import (
    BulkIn, CountOut, EventOut, MilestoneIn, MilestoneOut, MilestonePatch, Move, MyTaskOut, NoteIn, OverviewOut,
    ScheduleIn, ScheduleOut, TaskIn, TaskOut, TaskPatch,
)
from app.services import metrics, scheduler
from app.services.tasks import add_note, create_task, delete_task, update_task

router = APIRouter(prefix="/api", tags=["tasks"])


def _task_access(task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> tuple[Task, ProjectMember]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
    return task, membership(db, task.project_id, user)


def _milestone_access(milestone_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Milestone:
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Milestone not found.")
    require_manager(membership(db, milestone.project_id, user))
    return milestone


def _out(task: Task, deps: dict, slots: dict | None = None) -> TaskOut:
    slot = (slots or {}).get(task.id)
    return TaskOut.model_validate(task).model_copy(update={
        "depends_on": deps.get(task.id, []),
        "forecast_start": slot.start if slot else None,
        "forecast_finish": slot.finish if slot else None,
        "at_risk": bool(slot and slot.assignee and slot.at_risk),
    })


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    project = db.get(Project, member.project_id)
    tasks = db.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.position, Task.created_at)).all()
    deps = scheduler.dependencies(db, project.id)
    # Forecast with today's assignments: nothing moves, it only says when each task should be done.
    slots = scheduler.run(db, project, tasks, deps, movable=set())
    return [_out(t, deps, slots) for t in tasks]


@router.get("/projects/{project_id}/overview", response_model=OverviewOut)
def project_overview(member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    return metrics.overview(db, db.get(Project, member.project_id))


@router.get("/my/tasks", response_model=list[MyTaskOut])
def my_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your open tasks in every started project, soonest first. Draft plans stay out until they start."""
    rows = db.execute(
        select(Task, Project.name, Milestone.due_date, Project.deadline)
        .join(Project, Project.id == Task.project_id)
        .join(ProjectMember, (ProjectMember.project_id == Task.project_id) & (ProjectMember.user_id == user.id))
        .outerjoin(Milestone, Milestone.id == Task.milestone_id)
        .where(Task.assignee_id == user.id, Task.status != TaskStatus.done, Project.status == ProjectStatus.active)
    ).all()
    out = [
        MyTaskOut.model_validate({**TaskOut.model_validate(t).model_dump(), "project_name": name, "due": t.due_date or mdue or deadline})
        for t, name, mdue, deadline in rows
    ]
    return sorted(out, key=lambda t: (t.due or date.max, t.title))


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def add_task(body: TaskIn, member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    task = create_task(db, member.project_id, member.user_id, body)
    db.commit()
    return _out(task, {task.id: body.depends_on})


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def edit_task(body: TaskPatch, access: tuple[Task, ProjectMember] = Depends(_task_access), db: Session = Depends(get_db)):
    task, member = access
    update_task(db, task, member.user_id, body.model_dump(exclude_unset=True))
    db.commit()
    return _out(task, scheduler.dependencies(db, task.project_id))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_task(access: tuple[Task, ProjectMember] = Depends(_task_access), db: Session = Depends(get_db)):
    task, member = access
    require_manager(member)
    delete_task(db, task, member.user_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects/{project_id}/tasks/bulk", response_model=CountOut)
def bulk_edit(body: BulkIn, member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    tasks = db.scalars(select(Task).where(Task.id.in_(body.ids), Task.project_id == member.project_id)).all()
    if len(tasks) != len(set(body.ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Some of those tasks aren't in this project.")
    if body.delete:
        require_manager(member)
        for task in tasks:
            delete_task(db, task, member.user_id)
    elif body.changes is not None:
        changes = body.changes.model_dump(exclude_unset=True)
        for task in tasks:
            update_task(db, task, member.user_id, changes)
    db.commit()  # all or nothing: one bad task fails the whole batch
    return CountOut(count=len(tasks))


@router.get("/tasks/{task_id}/events", response_model=list[EventOut])
def task_history(access: tuple[Task, ProjectMember] = Depends(_task_access), db: Session = Depends(get_db)):
    task, _ = access
    rows = db.execute(
        select(TaskEvent, User.name).outerjoin(User, User.id == TaskEvent.actor_id)
        .where(TaskEvent.task_id == task.id).order_by(TaskEvent.created_at.desc()).limit(200)
    ).all()
    return [
        EventOut(id=e.id, task_id=e.task_id, actor_name=name, kind=e.kind, source=e.source, data=e.data, created_at=e.created_at)
        for e, name in rows
    ]


@router.post("/tasks/{task_id}/notes", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def note_task(body: NoteIn, access: tuple[Task, ProjectMember] = Depends(_task_access), db: Session = Depends(get_db)):
    task, member = access
    event = add_note(db, task, member.user_id, body.text)
    db.commit()
    actor = db.get(User, member.user_id)
    return EventOut(id=event.id, task_id=task.id, actor_name=actor.name, kind=event.kind, source=event.source, data=event.data, created_at=event.created_at)


@router.post("/projects/{project_id}/schedule", response_model=ScheduleOut)
def schedule(body: ScheduleIn, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    """Rebalance: reassign unstarted tasks nobody assigned by hand. Preview unless `apply` is set."""
    project = db.get(Project, member.project_id)
    tasks = db.scalars(select(Task).where(Task.project_id == project.id)).all()
    movable = scheduler.movable_ids(tasks)
    slots = scheduler.run(db, project, tasks, scheduler.dependencies(db, project.id), movable)
    moves = [
        Move(task_id=t.id, title=t.title, from_assignee_id=t.assignee_id, to_assignee_id=slots[t.id].assignee,
             note=slots[t.id].note, finish=slots[t.id].finish, at_risk=slots[t.id].at_risk)
        for t in tasks if t.id in movable and slots[t.id].assignee != t.assignee_id
    ]
    if body.apply:
        for t in tasks:
            if t.id in movable:
                update_task(db, t, member.user_id, {"assignee_id": slots[t.id].assignee, "assignment_note": slots[t.id].note}, EventSource.ai)
        db.commit()
    finishes = [s.finish for s in slots.values() if s.assignee and s.finish]
    return ScheduleOut(
        moves=moves,
        predicted_finish=max(finishes) if finishes else None,
        at_risk=sum(1 for s in slots.values() if s.assignee and s.at_risk),
        applied=body.apply,
    )


@router.post("/projects/{project_id}/milestones", response_model=MilestoneOut, status_code=status.HTTP_201_CREATED)
def add_milestone(body: MilestoneIn, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    last = db.scalar(select(Milestone.position).where(Milestone.project_id == member.project_id).order_by(Milestone.position.desc()).limit(1))
    milestone = Milestone(project_id=member.project_id, position=(last or 0) + 1, **body.model_dump())
    db.add(milestone)
    db.commit()
    return milestone


@router.patch("/milestones/{milestone_id}", response_model=MilestoneOut)
def edit_milestone(body: MilestonePatch, milestone: Milestone = Depends(_milestone_access), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field in ("title", "description", "position"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field.capitalize()} can't be empty.")
        setattr(milestone, field, value)
    db.commit()
    return milestone


@router.delete("/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_milestone(milestone: Milestone = Depends(_milestone_access), db: Session = Depends(get_db)):
    db.delete(milestone)  # its tasks stay, without a milestone (ON DELETE SET NULL)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
