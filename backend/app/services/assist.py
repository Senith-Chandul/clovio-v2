"""Voice and typed commands: "supplies are delivered" becomes a change to the right task.

The AI only sees numbered task lists and may only answer with a fixed set of actions. Every action is checked
here (task numbers it was given, valid values, people in that project) and applied through the one task write
path, so history and permissions hold. Nothing is ever deleted this way.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models import EventSource, Milestone, Project, ProjectMember, Task, TaskStatus, User
from app.schemas import Applied, AssistOut, Choice, TaskIn, TaskPatch
from app.services.llm import complete_json
from app.services.tasks import add_note, create_task, update_task

MAX_CANDIDATES = 150
MAX_ACTIONS = 5
STATUS_WORDS = {"todo": "moved back to to do", "in_progress": "started", "blocked": "marked blocked", "done": "marked done"}

SYSTEM = (
    "You turn what a team member says or types into changes to their project tasks. "
    "Match by meaning, not exact words. Never invent task numbers. Always reply with one JSON object and nothing else."
)


class AIAction(BaseModel):
    type: Literal["update", "create"] = "update"
    task: int | None = None
    status: TaskStatus | None = None
    note: str | None = None
    estimate_hours: float | None = None
    due_date: date | None = None
    assignee: str | None = None
    title: str | None = None


class AIAsk(BaseModel):
    question: str = "Which task did you mean?"
    tasks: list[int] = []


class AIAssist(BaseModel):
    actions: list[AIAction] = []
    ask: AIAsk | None = None
    answer: str | None = None


@dataclass
class Candidate:
    task: Task
    project_name: str
    assignee_name: str | None
    due: date | None


def _candidates(db: Session, user: User, project_id: uuid.UUID | None) -> list[Candidate]:
    """Open tasks in the user's projects (one project if given), their own first, then by date."""
    assignee = aliased(User)
    query = (
        select(Task, Project.name, assignee.name, Task.due_date, Milestone.due_date, Project.deadline)
        .join(Project, Project.id == Task.project_id)
        .join(ProjectMember, (ProjectMember.project_id == Task.project_id) & (ProjectMember.user_id == user.id))
        .outerjoin(Milestone, Milestone.id == Task.milestone_id)
        .outerjoin(assignee, assignee.id == Task.assignee_id)
        .where(Task.status != TaskStatus.done)
    )
    if project_id:
        query = query.where(Task.project_id == project_id)
    found = [Candidate(t, pname, aname, tdue or mdue or deadline) for t, pname, aname, tdue, mdue, deadline in db.execute(query)]
    found.sort(key=lambda c: (c.task.assignee_id != user.id, c.due or date.max, c.task.title))
    return found[:MAX_CANDIDATES]


def _line(n: int, c: Candidate, many_projects: bool) -> str:
    parts = [f"[{n}] {c.task.title}", c.task.status.replace("_", " "), c.assignee_name or "unassigned"]
    if c.due:
        parts.append(f"due {c.due}")
    if many_projects:
        parts.append(f"project {c.project_name}")
    return " | ".join(parts)


def _people(db: Session, project_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[tuple[str, uuid.UUID]]]:
    people: dict[uuid.UUID, list[tuple[str, uuid.UUID]]] = {pid: [] for pid in project_ids}
    rows = db.execute(select(ProjectMember.project_id, User.name, User.id).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id.in_(project_ids)))
    for pid, name, uid in rows:
        people[pid].append((name, uid))
    return people


def _resolve(name: str, members: list[tuple[str, uuid.UUID]]) -> uuid.UUID | None:
    """A person by full name, or by first name when only one member has it."""
    wanted = " ".join(name.lower().split())
    exact = [uid for n, uid in members if n.lower() == wanted]
    if exact:
        return exact[0]
    first = [uid for n, uid in members if n.lower().split()[0] == wanted.split()[0]] if wanted else []
    return first[0] if len(first) == 1 else None


def hint(db: Session, user: User, project_id: uuid.UUID | None) -> str:
    """Words for the speech-to-text to expect: people's names and task titles."""
    candidates = _candidates(db, user, project_id)
    names = sorted({n for members in _people(db, {c.task.project_id for c in candidates}).values() for n, _ in members})
    return f"People: {', '.join(names)}. Tasks: {'; '.join(c.task.title for c in candidates[:25])}."


def run(
    db: Session, user: User, text: str, source: EventSource,
    project_id: uuid.UUID | None = None, task_id: uuid.UUID | None = None,
) -> AssistOut:
    text = text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say or type what changed.")
    candidates = _candidates(db, user, project_id)
    if task_id:  # they were looking at this task: put it first so "this is done" lands on it
        candidates.sort(key=lambda c: c.task.id != task_id)
    if not candidates:
        return AssistOut(transcript=text, reply="There are no open tasks to change.", answered=False, applied=[], choices=[])
    many = len({c.task.project_id for c in candidates}) > 1
    people = _people(db, {c.task.project_id for c in candidates})
    names = sorted({n for members in people.values() for n, _ in members})
    looking = "They have task [1] open on screen, so a bare \"done\" or \"this\" means that one.\n" if task_id and candidates[0].task.id == task_id else ""

    today = date.today()
    # The model can't work out weekdays reliably ("by Friday" came back as a Sunday), so spell the week out.
    week = ", ".join(f"{d:%A} {d}" for d in (today + timedelta(days=i) for i in range(8)))
    prompt = f"""Today is {today:%A} {today}. The coming days: {week}.
{user.name} said: "{text}"
{looking}
Open tasks (number | title | status | assignee | due date):
{chr(10).join(_line(i, c, many) for i, c in enumerate(candidates, start=1))}

People: {", ".join(names)}

How to read it:
- Something finished ("supplies are delivered", "venue's booked") means status "done". Started means "in_progress". Stuck or waiting on someone means "blocked".
- Partial progress ("half the chairs came") keeps the status and adds a short note.
- If they say how long something takes ("about 3 hours"), set estimate_hours. If they say when it must be done ("by Friday"), set due_date.
- If the words fit two or more tasks equally well (say "the order is done" when there are two order tasks), change nothing and ask, listing their numbers, even if one of them is the speaker's.
- A question ("what's left for catering?") gets an answer from the list above, in at most two short plain sentences with dates written like "3 Dec", and changes nothing.
- Use "create" only when they clearly ask for a new task. Never delete anything. At most {MAX_ACTIONS} actions.
Reply as {{"actions": [{{"type": "update", "task": 1, "status": "done", "note": null, "estimate_hours": null, "due_date": null, "assignee": null, "title": null}}], "ask": null, "answer": null}}
or {{"actions": [], "ask": {{"question": "Which supplies task?", "tasks": [2, 5]}}, "answer": null}}."""
    db.commit()  # release the connection during the AI call
    plan = complete_json(SYSTEM, prompt, AIAssist)

    def pick(n: int | None) -> Candidate | None:
        return candidates[n - 1] if n is not None and 1 <= n <= len(candidates) else None

    if plan.ask and not plan.actions:
        choices = [Choice(task_id=c.task.id, title=c.task.title, project_name=c.project_name) for c in map(pick, plan.ask.tasks) if c]
        if choices:
            return AssistOut(transcript=text, reply=plan.ask.question, answered=False, applied=[], choices=choices)
    if plan.answer and not plan.actions:
        return AssistOut(transcript=text, reply=plan.answer.strip(), answered=True, applied=[], choices=[])

    applied: list[Applied] = []
    problems: list[str] = []
    for action in plan.actions[:MAX_ACTIONS]:
        if action.type == "create":
            if not project_id:
                problems.append("open a project to add tasks to it")
                continue
            members = people.get(project_id) or _people(db, {project_id})[project_id]
            assignee_id = _resolve(action.assignee, members) if action.assignee else None
            try:
                data = TaskIn(title=(action.title or "")[:300], due_date=action.due_date, assignee_id=assignee_id,
                              estimate_hours=action.estimate_hours if action.estimate_hours and 0 < action.estimate_hours <= 1000 else None)
            except ValidationError:
                problems.append("a new task needs a title")
                continue
            task = create_task(db, project_id, user.id, data, source)
            if source == EventSource.voice:
                add_note(db, task, user.id, text, source)
            applied.append(Applied(task_id=task.id, project_id=project_id, title=task.title, summary="added", previous=TaskPatch()))
            continue

        candidate = pick(action.task)
        if candidate is None:
            continue
        task, changes, said = candidate.task, {}, []
        if action.status and action.status != task.status:
            changes["status"] = action.status
            said.append(STATUS_WORDS[action.status])
        if action.estimate_hours and 0 < action.estimate_hours <= 1000:
            changes["estimate_hours"] = action.estimate_hours
            said.append(f"estimate {action.estimate_hours:g} h")
        if action.due_date:
            changes["due_date"] = action.due_date
            said.append(f"due {action.due_date:%a} {action.due_date.day} {action.due_date:%b}")
        if action.assignee:
            person = _resolve(action.assignee, people[task.project_id])
            if person is None:
                problems.append(f"no one called {action.assignee} is in {candidate.project_name}")
            else:
                changes["assignee_id"] = person
                said.append(f"given to {next(n for n, uid in people[task.project_id] if uid == person)}")
        previous = TaskPatch(**{field: getattr(task, field) for field in changes})
        if changes:
            update_task(db, task, user.id, changes, source)
        # The spoken words go into the history as evidence; a typed command only leaves a note when it carries one.
        note = text if source == EventSource.voice else (action.note or "").strip()
        if note:
            add_note(db, task, user.id, note[:4000], source)
            said.append("note added")
        if said:
            applied.append(Applied(task_id=task.id, project_id=task.project_id, title=task.title, summary=", ".join(said), previous=previous))
    db.commit()

    if applied:
        reply = "; ".join(f"{a.title}: {a.summary}" for a in applied) + "."
    else:
        reply = "I couldn't match that to a task. Try saying the task's name."
    if problems:
        reply += " Not done: " + "; ".join(problems) + "."
    return AssistOut(transcript=text, reply=reply, answered=False, applied=applied, choices=[])
