"""The project overview: how it's going, worked out on each read from the tasks and one scheduler forecast."""

import statistics
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Milestone, Project, Task, TaskStatus
from app.schemas import MilestoneProgress, OverviewOut, PersonLoad
from app.services import scheduler


def overview(db: Session, project: Project, today: date | None = None) -> OverviewOut:
    today = today or date.today()
    tasks = db.scalars(select(Task).where(Task.project_id == project.id)).all()
    milestones = db.scalars(select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.position)).all()
    milestone_due = {m.id: m.due_date for m in milestones}
    slots = scheduler.run(db, project, tasks, scheduler.dependencies(db, project.id), movable=set())

    def due(t: Task) -> date | None:
        return t.due_date or milestone_due.get(t.milestone_id) or project.deadline

    def hours(t: Task) -> float:
        return t.estimate_hours or scheduler.DEFAULT_HOURS

    done = [t for t in tasks if t.status == TaskStatus.done]
    open_ = [t for t in tasks if t.status != TaskStatus.done]
    total_hours = sum(hours(t) for t in tasks)

    # shortcut: completion is compared as a UTC date with the local due date; fine unless people work past midnight UTC.
    finished_with_due = [t for t in done if due(t) and t.completed_at]
    on_time = sum(t.completed_at.date() <= due(t) for t in finished_with_due)
    # Tasks moved straight to done have no measurable cycle, so they're left out.
    cycles = [(t.completed_at - t.started_at).total_seconds() / 86400 for t in done
              if t.started_at and t.completed_at and t.completed_at > t.started_at]
    finishes = [slots[t.id].finish for t in open_ if t.id in slots and slots[t.id].finish]

    open_hours, overdue_by = defaultdict(float), defaultdict(int)
    for t in open_:
        if t.assignee_id:
            open_hours[t.assignee_id] += hours(t)
            if due(t) and due(t) < today:
                overdue_by[t.assignee_id] += 1
    days_left = (project.deadline - today).days + 1 if project.deadline else None
    people = []
    for person in scheduler.people(db, project.id):
        free = round(scheduler.free_hours(person, days_left), 1) if days_left is not None else None
        mine = round(open_hours[person.id], 1)
        people.append(PersonLoad(user_id=person.id, name=person.name, open_hours=mine, free_hours=free,
                                 bottleneck=free is not None and mine > free, overdue=overdue_by[person.id]))

    progress = []
    for m in milestones:
        mine = [t for t in tasks if t.milestone_id == m.id]
        ends = [slots[t.id].finish for t in mine if t.status != TaskStatus.done and t.id in slots and slots[t.id].finish]
        finish = max(ends, default=None)
        unfinished = any(t.status != TaskStatus.done for t in mine)
        late = bool(m.due_date and unfinished and ((finish and finish > m.due_date) or m.due_date < today))
        progress.append(MilestoneProgress(id=m.id, title=m.title, due_date=m.due_date, done=sum(t.status == TaskStatus.done for t in mine),
                                          total=len(mine), forecast_finish=finish, late=late))

    return OverviewOut(
        progress=sum(hours(t) for t in done) / total_hours if total_hours else 0.0,
        tasks_total=len(tasks),
        tasks_done=len(done),
        overdue=sum(1 for t in open_ if due(t) and due(t) < today),
        blocked=sum(t.status == TaskStatus.blocked for t in open_),
        at_risk=sum(1 for t in open_ if t.id in slots and slots[t.id].assignee and slots[t.id].at_risk),
        unassigned=sum(t.assignee_id is None for t in open_),
        on_time_rate=on_time / len(finished_with_due) if finished_with_due else None,
        on_time_of=len(finished_with_due),
        cycle_days=round(statistics.median(cycles), 1) if cycles else None,
        deadline=project.deadline,
        predicted_finish=max(finishes, default=None),
        people=sorted(people, key=lambda p: (-p.open_hours, p.name)),
        milestones=progress,
    )
