"""The AI side of the wizard: questions about the brief, the milestones, then each milestone's tasks.
The AI never picks people; the scheduler does that.

Each function gathers what the prompt needs, then commits before calling the AI, so no database connection
sits idle in a transaction for the seconds the AI takes (pooled connections are scarce on Supabase).
"""

import uuid
from datetime import date

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventSource, Milestone, Project, ProjectMember, Task, User
from app.schemas import TaskIn, clean_skills
from app.services.llm import complete_json
from app.services.tasks import create_task, set_dependencies

SYSTEM = (
    "You plan projects of any kind: events, software, marketing, research, operations and more. "
    "Your plans are concrete, specific to the brief, and realistic about time. "
    "Write in plain words and sentence case. Always reply with one JSON object and nothing else."
)
MAX_TASKS = 25


class AIQuestions(BaseModel):
    questions: list[str] = []


class AIMilestone(BaseModel):
    title: str
    description: str = ""
    due_date: date | None = None


class AIOutline(BaseModel):
    name: str = ""
    milestones: list[AIMilestone]


class AITask(BaseModel):
    title: str
    description: str = ""
    estimate_hours: float | None = None
    required_skills: list[str] = []
    depends_on: list[str] = []


class AITasks(BaseModel):
    tasks: list[AITask]


def _team(db: Session, project_id: uuid.UUID) -> list[User]:
    return db.scalars(select(User).join(ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == project_id)).all()


def _team_lines(team: list[User]) -> str:
    return "\n".join(f"- {u.name}: {', '.join(u.skills) or 'no skills listed'} ({u.weekly_hours:g} h a week)" for u in team)


def _clamp(day: date | None, low: date, high: date | None) -> date | None:
    if day is None:
        return None
    day = max(day, low)
    return min(day, high) if high else day


def _key(title: str) -> str:
    return " ".join(title.lower().split())


def _sentence_case(title: str) -> str:
    """The AI writes milestone titles in Title Case even when told not to. Only a title whose longer words are all
    capitalised is changed, and acronyms (AV, RSVP) stay. shortcut: a proper noun in such a title gets lowercased;
    if that bites, ask for titles in a JSON schema with examples."""
    words = title.split()
    longer = [w for w in words[1:] if len(w) > 3]
    if not longer or not all(w[0].isupper() for w in longer):
        return title
    return " ".join([words[0]] + [w.lower() if w[1:].islower() else w for w in words[1:]])


def questions(db: Session, project: Project) -> list[str]:
    team = _team(db, project.id)
    prompt = f"""Brief:
{project.brief or "(no brief yet)"}

Today: {date.today()}. Deadline: {project.deadline or "not set"}. Team: {len(team)} people.

Ask at most 3 short questions whose answers would change the plan the most, such as scale, what is already done or booked, or hard constraints. Don't ask anything the brief already answers. If the brief is clear enough, ask none.
Reply as {{"questions": ["..."]}}."""
    db.commit()
    answer = complete_json(SYSTEM, prompt, AIQuestions)
    return [q.strip() for q in answer.questions if q.strip()][:3]


def outline(db: Session, project: Project, answers: list[tuple[str, str]]) -> list[Milestone]:
    """Create the milestones (once per project) and name the project if it has no name yet."""
    if db.scalar(select(Milestone.id).where(Milestone.project_id == project.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This project already has milestones.")
    answered = [(q, a.strip()) for q, a in answers if a.strip()]
    brief = project.brief
    if answered:
        brief = (brief + "\n\nAnswers to the planner's questions:\n" + "\n".join(f"- {q} {a}" for q, a in answered)).strip()
    today = date.today()
    prompt = f"""Brief:
{brief or "(no brief)"}

Today: {today}. Deadline: {project.deadline or "none set, so propose realistic dates"}.
Team:
{_team_lines(_team(db, project.id))}

Split the work into 2 to 7 milestones: phases in the order they happen, each ending in something you can check. For each give a short title in sentence case (like "Venue and suppliers booked", not "Venue And Suppliers Booked"), one sentence on what is true when it's done, and a due date (YYYY-MM-DD) between today and the deadline, in order, with the last one on or before the deadline and time left for final checks.
The deadline is when everything must be finished (for an event, the event day itself). Leave out anything that happens after it.
Put work that involves waiting (bookings, orders, printing, approvals) in the earliest milestones, so there's time for the wait.
Milestones must not overlap: each piece of work (say, the catering contract or the banners) belongs to exactly one milestone, and its description says what that milestone covers.
Also suggest a short project name, at most five words.
Reply as {{"name": "...", "milestones": [{{"title": "...", "description": "...", "due_date": "YYYY-MM-DD"}}]}}."""
    db.commit()
    plan = complete_json(SYSTEM, prompt, AIOutline)

    project.brief = brief  # saved only now, so a failed call and a retry don't add the answers twice
    if not project.name.strip():
        project.name = plan.name.strip()[:200] or "New project"
    milestones, previous = [], today
    for position, m in enumerate(plan.milestones[:7], start=1):
        if not m.title.strip():
            continue
        # Dates stay between today and the deadline, and never run backwards.
        due = _clamp(m.due_date, previous, project.deadline)
        previous = due or previous
        milestone = Milestone(project_id=project.id, title=_sentence_case(m.title.strip())[:200], description=m.description.strip()[:2000], position=position, due_date=due)
        db.add(milestone)
        milestones.append(milestone)
    if not milestones:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI didn't suggest any milestones. Try again, or add more detail to the brief.")
    db.commit()
    return milestones


def milestone_tasks(db: Session, project: Project, milestone: Milestone, actor_id: uuid.UUID) -> list[Task]:
    """Generate one milestone's tasks and save them in one transaction. Refuses a milestone that already has tasks."""
    if db.scalar(select(Task.id).where(Task.milestone_id == milestone.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This milestone already has tasks.")
    all_milestones = db.scalars(select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.position)).all()
    before = [m for m in all_milestones if m.position < milestone.position]
    start = max([m.due_date for m in before if m.due_date] + [date.today()])
    end = milestone.due_date or project.deadline
    team = _team(db, project.id)
    vocabulary = sorted({s for u in team for s in u.skills})
    prompt = f"""Brief:
{project.brief or "(no brief)"}

Plan this milestone only: "{milestone.title}". {milestone.description}
Work on it can start {start} and must be done by {end or "a realistic date"}.
All milestones, in order (each is planned separately, so only list work that belongs to this one, and don't list the same work twice):
{chr(10).join(f"- {m.title}: {m.description}" for m in all_milestones)}
Skills the team has: {", ".join(vocabulary) or "none listed"}.
Team, with the hours a week each can give:
{_team_lines(team)}

List the concrete tasks needed to finish this milestone, usually 3 to 10. For each task give:
- title: a short action, like "Book the venue"
- description: one or two sentences on what done looks like
- estimate_hours: hands-on working hours for one person, not waiting time, between 0.5 and 40
- required_skills: 1 to 3 short lowercase skill words; reuse the team's skill words when one fits
- depends_on: titles of tasks in this list that must be finished first, or []
Don't assign people or set dates; that happens separately, from everyone's free hours.
Reply as {{"tasks": [{{"title": "...", "description": "...", "estimate_hours": 2, "required_skills": ["..."], "depends_on": []}}]}}."""
    db.commit()
    plan = complete_json(SYSTEM, prompt, AITasks)

    # Recheck after the AI call: a second request for the same milestone may have saved its tasks meanwhile.
    db.scalar(select(Milestone).where(Milestone.id == milestone.id).with_for_update())
    if db.scalar(select(Task.id).where(Task.milestone_id == milestone.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This milestone already has tasks.")
    created: dict[str, tuple[Task, list[str]]] = {}
    for t in plan.tasks[:MAX_TASKS]:
        try:
            data = TaskIn(
                title=t.title[:300],
                description=t.description[:10_000],
                milestone_id=milestone.id,
                estimate_hours=min(max(t.estimate_hours, 0.5), 200) if t.estimate_hours else None,
                # No due date: the milestone's date applies. The AI's per-task dates were guesses spread across
                # the milestone, and flagged noise as "at risk"; a person can still set one by hand.
                required_skills=clean_skills(t.required_skills)[:3],
            )
        except ValidationError:
            continue  # e.g. an empty title: skip that task, keep the plan
        if _key(data.title) not in created:
            created[_key(data.title)] = (create_task(db, project.id, actor_id, data, EventSource.ai), t.depends_on)
    for task, wanted in created.values():
        ids = [created[_key(w)][0].id for w in wanted if _key(w) in created and created[_key(w)][0].id != task.id]
        if ids:
            try:
                set_dependencies(db, task, ids)
            except HTTPException:
                pass  # the AI drew a loop: drop those links rather than the plan
    if not created:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI didn't suggest any tasks for this milestone. Try again.")
    db.commit()
    return [task for task, _ in created.values()]
