"""Who does what, and when it will be done. The AI writes the plan; this assigns it.

`plan()` is pure and deterministic (same input, same answer), so it's cheap to run on every read and easy to test.
The functions under it load its input from the database.
"""

import heapq
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Milestone, Project, ProjectMember, Task, TaskDependency, TaskStatus, User
from app.services import calendars

DEFAULT_HOURS = 1.0  # a task with no estimate still takes some time
HORIZON_DAYS = 365
DAILY_CAP = 8.0  # nobody works more than this in one day, however many hours a week they give


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    name: str
    skills: frozenset[str]
    weekly_hours: float
    booked: float = 0.0  # open hours already assigned in other projects, worked first
    busy: tuple[float, ...] = ()  # calendar hours taken in each working day, from today; unknown days count as free


@dataclass(frozen=True)
class Job:
    id: uuid.UUID
    hours: float
    due: date | None
    skills: frozenset[str]
    depends_on: frozenset[uuid.UUID]
    assignee: uuid.UUID | None
    movable: bool  # the scheduler may choose the person


@dataclass(frozen=True)
class Slot:
    assignee: uuid.UUID | None
    finish: date | None  # None: no person, or it doesn't fit within the horizon
    at_risk: bool
    note: str
    start: date | None = None  # the first day work on it is planned


def _fmt(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _join(words) -> str:
    return ", ".join(sorted(words))


class _Time:
    """One person's free hours: their weekly hours to spend in each 7-day block from today, at most DAILY_CAP a day
    less what their calendar has booked that day. A budget, not an even spread: 10 hours a week can all go on Monday,
    unless Monday is full of meetings."""

    def __init__(self, weekly: float, horizon: int, busy: tuple[float, ...] = ()):
        self.day = [max(0.0, min(DAILY_CAP, weekly, DAILY_CAP - (busy[i] if i < len(busy) else 0.0))) for i in range(horizon)]
        self.week = [weekly] * (horizon // 7 + 1)

    def fill(self, start: int, hours: float) -> tuple[int | None, list[tuple[int, float]]]:
        """The day index work started on `start` is done (None if it doesn't fit), and the hours it uses per day."""
        if hours <= 0:
            return start, []
        takes, left = [], hours
        spent = defaultdict(float)  # this job's hours per week so far, so a week's budget isn't spent twice
        for i in range(start, len(self.day)):
            free = min(self.day[i], self.week[i // 7] - spent[i // 7])
            if free > 1e-9:
                used = min(free, left)
                takes.append((i, used))
                spent[i // 7] += used
                left -= used
                if left <= 1e-9:
                    return i, takes
        return None, takes

    def book(self, takes: list[tuple[int, float]]) -> None:
        for i, used in takes:
            self.day[i] -= used
            self.week[i // 7] -= used


def _order(jobs: list[Job]) -> list[Job]:
    """Prerequisites first; otherwise the earliest due date, then the biggest job."""
    index = {job.id: i for i, job in enumerate(jobs)}
    by_id = {job.id: job for job in jobs}
    waiting = {job.id: {d for d in job.depends_on if d in by_id} for job in jobs}
    dependents = defaultdict(list)
    for job in jobs:
        for d in waiting[job.id]:
            dependents[d].append(job.id)

    def key(job: Job):
        return (job.due or date.max, -job.hours, index[job.id])

    ready = [(key(job), job.id) for job in jobs if not waiting[job.id]]
    heapq.heapify(ready)
    order: list[Job] = []
    while ready:
        _, job_id = heapq.heappop(ready)
        order.append(by_id[job_id])
        for other in dependents[job_id]:
            waiting[other].discard(job_id)
            if not waiting[other]:
                heapq.heappush(ready, (key(by_id[other]), other))
    # The write path refuses loops, but a job caught in one is still scheduled rather than dropped.
    placed = {job.id for job in order}
    return order + sorted((job for job in jobs if job.id not in placed), key=key)


def plan(jobs: list[Job], people: list[Person], today: date, horizon_days: int = HORIZON_DAYS) -> dict[uuid.UUID, Slot]:
    """Assign movable jobs and forecast every job's finish.

    For a movable job the candidates are the people with the best skill match; if none of them can make the due
    date, someone with a weaker match who can is preferred. Among equals, whoever finishes first gets it.
    """
    time = {person.id: _Time(person.weekly_hours, horizon_days, person.busy) for person in people}
    for person in people:
        time[person.id].book(time[person.id].fill(0, person.booked)[1])
    booked = {person.id: person.booked for person in people}
    by_id = {person.id: person for person in people}
    finished_on: dict[uuid.UUID, int] = {}
    slots: dict[uuid.UUID, Slot] = {}

    for job in _order(jobs):
        start = max((finished_on[d] for d in job.depends_on if d in finished_on), default=0)

        def _skill_matches(req: str, owned: frozenset[str]) -> bool:
            r = req.lower().strip()
            if not r:
                return False
            if r in owned:
                return True
            r_tokens = {w for w in r.replace("&", " ").replace("/", " ").replace("-", " ").split() if len(w) >= 2}
            for s in owned:
                s_low = s.lower().strip()
                if r in s_low or s_low in r:
                    return True
                s_tokens = {w for w in s_low.replace("&", " ").replace("/", " ").replace("-", " ").split() if len(w) >= 2}
                if r_tokens and (r_tokens & s_tokens):
                    return True
            return False

        def matched_skills(person: Person) -> set[str]:
            return {req for req in job.skills if _skill_matches(req, person.skills)}

        def score(person: Person) -> float:
            return len(matched_skills(person)) / len(job.skills) if job.skills else 1.0

        if job.movable and people:
            best = max(score(p) for p in people)
            pool = [p for p in people if score(p) > 0] if best > 0 else people
            options = []
            for person in pool:
                end, takes = time[person.id].fill(start, job.hours)
                late = end is None or (job.due is not None and today + timedelta(days=end) > job.due)
                rank = (late, -score(person), end if end is not None else math.inf, booked[person.id], person.name, str(person.id))
                options.append((rank, person, end, takes))
            _, person, end, takes = min(options, key=lambda option: option[0])
        else:
            person = by_id.get(job.assignee) if job.assignee else None
            if person is None:
                note = "Unassigned" if job.assignee is None else "Assigned to someone who's no longer in the project"
                slots[job.id] = Slot(job.assignee, None, False, note)
                continue
            end, takes = time[person.id].fill(start, job.hours)

        time[person.id].book(takes)
        booked[person.id] += job.hours
        finished_on[job.id] = end if end is not None else horizon_days
        finish = today + timedelta(days=end) if end is not None else None
        at_risk = finish is None or (job.due is not None and finish > job.due)

        if job.movable:
            if job.skills and best == 0:
                why = f"No one lists {_join(job.skills)}; {person.name} can finish it soonest"
            elif job.skills:
                why = f"Has {_join(matched_skills(person))}"
                if score(person) < best:
                    why += " (closer matches can't make the due date)"
            else:
                why = "Free soonest"
        else:
            why = "Assigned"
        note = f"{why} · finishes {_fmt(finish)}" if finish else f"{why} · doesn't fit in the next {horizon_days} days"
        if finish and at_risk:
            note += f" · at risk: due {_fmt(job.due)}"
        slots[job.id] = Slot(person.id, finish, at_risk, note, today + timedelta(days=takes[0][0]) if takes else None)
    return slots


def free_hours(person: Person, days: int) -> float:
    """Hours a person can still give over the next `days` days (today included), after their other projects."""
    time = _Time(person.weekly_hours, max(days, 0), person.busy)
    time.book(time.fill(0, person.booked)[1])
    return sum(used for _, used in time.fill(0, math.inf)[1])


# ── Loading the input from the database ─────────────────────────────────────


def people(db: Session, project_id: uuid.UUID) -> list[Person]:
    users = db.scalars(select(User).join(ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == project_id)).all()
    elsewhere = dict(
        db.execute(
            select(Task.assignee_id, func.sum(func.coalesce(Task.estimate_hours, DEFAULT_HOURS)))
            .where(Task.assignee_id.in_([u.id for u in users]), Task.project_id != project_id, Task.status != TaskStatus.done)
            .group_by(Task.assignee_id)
        ).all()
    )
    # shortcut: a "week" is each 7-day block from today and any day can be worked, weekends included; skip
    # weekends if the client's people only work weekdays.
    today = date.today()
    out = []
    for u in users:
        times = calendars.busy(db, u)  # None: no calendar connected, so every day counts as free
        busy = calendars.busy_hours_by_day(times, u.timezone, today) if times else ()
        out.append(Person(u.id, u.name, frozenset(u.skills), u.weekly_hours, float(elsewhere.get(u.id) or 0), busy))
    return out


def dependencies(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, list[uuid.UUID]]:
    deps: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    rows = db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_id)
        .join(Task, Task.id == TaskDependency.task_id)
        .where(Task.project_id == project_id)
    )
    for task_id, depends_on_id in rows:
        deps[task_id].append(depends_on_id)
    return deps


def run(db: Session, project: Project, tasks: list[Task], deps: dict, movable: set[uuid.UUID]) -> dict[uuid.UUID, Slot]:
    """Plan the project's open tasks. Due dates fall back to the milestone's, then the project deadline."""
    milestone_due = dict(db.execute(select(Milestone.id, Milestone.due_date).where(Milestone.project_id == project.id)).all())
    jobs = [
        Job(
            id=t.id,
            hours=t.estimate_hours or DEFAULT_HOURS,
            due=t.due_date or milestone_due.get(t.milestone_id) or project.deadline,
            skills=frozenset(t.required_skills),
            depends_on=frozenset(deps.get(t.id, ())),
            assignee=t.assignee_id,
            movable=t.id in movable,
        )
        for t in tasks
        if t.status != TaskStatus.done
    ]
    return plan(jobs, people(db, project.id), date.today())


def movable_ids(tasks: list[Task]) -> set[uuid.UUID]:
    """What a rebalance may move: tasks nobody has started and nobody assigned by hand."""
    return {t.id for t in tasks if t.status == TaskStatus.todo and not t.assignee_locked}
