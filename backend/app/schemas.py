"""Request and response shapes shared by the routers. The frontend's types are generated from these."""

import uuid
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models import ConversationKind, EventKind, EventSource, ProjectStatus, Provider, Role, TaskStatus


def clean_skills(skills: list[str]) -> list[str]:
    """Lowercased and trimmed, without blanks or repeats, so the scheduler can compare them as plain words."""
    cleaned: list[str] = []
    for skill in skills:
        skill = " ".join(skill.lower().split())
        if skill and skill not in cleaned:
            cleaned.append(skill)
    return cleaned


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Skills = Annotated[list[Annotated[str, StringConstraints(max_length=40)]], Field(max_length=20), AfterValidator(clean_skills)]
WeeklyHours = Annotated[float, Field(ge=0, le=100)]
TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
TaskHours = Annotated[float, Field(gt=0, le=1000)]


def _known_zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown time zone.")
    return name


TimeZone = Annotated[str, StringConstraints(max_length=64), AfterValidator(_known_zone)]


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(Orm):
    id: uuid.UUID
    email: str
    name: str
    weekly_hours: float
    timezone: str
    skills: list[str]


class MeIn(BaseModel):
    name: Name | None = None
    weekly_hours: WeeklyHours | None = None
    skills: Skills | None = None
    timezone: TimeZone | None = None  # set from the browser, so working hours and meeting times are local


class MemberIn(BaseModel):
    email: EmailStr
    name: Name | None = None
    role: Role = Role.member
    # Only used for people who haven't signed in yet; signed-in people keep their own profile.
    skills: Skills | None = None
    weekly_hours: WeeklyHours | None = None


class MemberPatch(BaseModel):
    role: Role | None = None
    name: Name | None = None
    skills: Skills | None = None
    weekly_hours: WeeklyHours | None = None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    skills: list[str]
    weekly_hours: float
    invited: bool  # hasn't signed in yet


class MilestoneIn(BaseModel):
    title: Name
    description: str = Field("", max_length=2000)
    due_date: date | None = None


class MilestonePatch(BaseModel):
    title: Name | None = None
    description: str | None = Field(None, max_length=2000)
    due_date: date | None = None
    position: int | None = None


class MilestoneOut(Orm):
    id: uuid.UUID
    title: str
    description: str
    position: int
    due_date: date | None


class ProjectIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""  # blank: the AI suggests one
    brief: str = Field("", max_length=50_000)
    deadline: date | None = None
    members: list[MemberIn] = Field(default_factory=list, max_length=100)


class ProjectPatch(BaseModel):
    name: Name | None = None
    brief: str | None = Field(None, max_length=50_000)
    deadline: date | None = None
    status: ProjectStatus | None = None


class ProjectSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: ProjectStatus
    deadline: date | None
    role: Role
    tasks_total: int
    tasks_done: int


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    brief: str
    status: ProjectStatus
    deadline: date | None
    created_at: datetime
    role: Role  # the signed-in user's role here
    members: list[MemberOut]
    milestones: list[MilestoneOut]


class TaskIn(BaseModel):
    id: uuid.UUID | None = None  # the browser may choose it, so an optimistic insert needs no id swap
    title: TaskTitle
    description: str = Field("", max_length=10_000)
    milestone_id: uuid.UUID | None = None
    status: TaskStatus = TaskStatus.todo
    estimate_hours: TaskHours | None = None
    due_date: date | None = None
    required_skills: Skills = []
    assignee_id: uuid.UUID | None = None
    depends_on: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class TaskPatch(BaseModel):
    """Only the fields sent are changed; send null to clear one that can be empty."""

    title: TaskTitle | None = None
    description: str | None = Field(None, max_length=10_000)
    milestone_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    estimate_hours: TaskHours | None = None
    due_date: date | None = None
    required_skills: Skills | None = None
    assignee_id: uuid.UUID | None = None
    position: float | None = None
    depends_on: list[uuid.UUID] | None = Field(None, max_length=50)


class TaskOut(Orm):
    id: uuid.UUID
    project_id: uuid.UUID
    milestone_id: uuid.UUID | None
    title: str
    description: str
    status: TaskStatus
    estimate_hours: float | None
    due_date: date | None
    required_skills: list[str]
    assignee_id: uuid.UUID | None
    assignee_locked: bool
    assignment_note: str
    position: float
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    depends_on: list[uuid.UUID] = []
    # From the scheduler with today's assignments: when work starts and should be done, and whether that's late.
    forecast_start: date | None = None
    forecast_finish: date | None = None
    at_risk: bool = False


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    changes: TaskPatch | None = None
    delete: bool = False


class CountOut(BaseModel):
    count: int


class NoteIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class EventOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    actor_name: str | None
    kind: EventKind
    source: EventSource
    data: dict
    created_at: datetime


class PersonLoad(BaseModel):
    user_id: uuid.UUID
    name: str
    open_hours: float
    free_hours: float | None  # between today and the deadline, after other projects; None without a deadline
    bottleneck: bool  # more open hours here than free hours before the deadline
    overdue: int


class MilestoneProgress(BaseModel):
    id: uuid.UUID
    title: str
    due_date: date | None
    done: int
    total: int
    forecast_finish: date | None
    late: bool


class OverviewOut(BaseModel):
    progress: float  # share of the estimated hours that are done
    tasks_total: int
    tasks_done: int
    overdue: int
    blocked: int
    at_risk: int
    unassigned: int
    on_time_rate: float | None  # of finished tasks that had a due date
    on_time_of: int
    cycle_days: float | None  # median days from in progress to done
    deadline: date | None
    predicted_finish: date | None
    people: list[PersonLoad]
    milestones: list[MilestoneProgress]


class CalendarOut(Orm):
    provider: Provider
    email: str
    needs_reconnect: bool


class CalendarsOut(BaseModel):
    accounts: list[CalendarOut]
    available: list[Provider]  # providers set up on this server, so the page only offers what works


class ConnectOut(BaseModel):
    url: str  # where the browser goes to connect the calendar


class MeetingIn(BaseModel):
    title: Name
    starts_at: AwareDatetime
    minutes: Annotated[int, Field(ge=15, le=480)]
    attendee_ids: Annotated[list[uuid.UUID], Field(max_length=100)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""


class MeetingOut(Orm):
    id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str
    organizer_id: uuid.UUID | None
    organizer_name: str | None = None
    attendee_emails: list[str]
    provider: Provider | None


class SuggestIn(BaseModel):
    attendee_ids: Annotated[list[uuid.UUID], Field(max_length=100)]
    minutes: Annotated[int, Field(ge=15, le=480)]


class SuggestOut(BaseModel):
    slots: list[datetime]
    unknown: list[str]  # people whose calendars couldn't be read, so the times don't account for them


class ChatOut(BaseModel):
    id: uuid.UUID
    kind: ConversationKind
    title: str  # the project's name, or the other person's
    project_id: uuid.UUID | None
    last_body: str | None
    last_sender: str | None
    last_at: datetime | None
    unread: int


class ChatPerson(BaseModel):
    user_id: uuid.UUID
    name: str


class ChatsOut(BaseModel):
    chats: list[ChatOut]
    people: list[ChatPerson]  # everyone you share a project with: who you can message directly


class DirectIn(BaseModel):
    user_id: uuid.UUID


class ChatRef(BaseModel):
    id: uuid.UUID


class MessageIn(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class MessageOut(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID | None
    sender_name: str | None
    body: str
    created_at: datetime


class NotificationOut(Orm):
    id: uuid.UUID
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    kind: str
    text: str
    created_at: datetime
    read_at: datetime | None


class NotificationsOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class Applied(BaseModel):
    task_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    summary: str  # e.g. "marked done, note added"
    previous: TaskPatch  # the changed fields' old values, so the app can offer Undo


class Choice(BaseModel):
    task_id: uuid.UUID
    title: str
    project_name: str


class AssistOut(BaseModel):
    transcript: str  # what was heard (or typed)
    reply: str
    answered: bool  # the reply is the AI's answer to a question, not a summary of changes
    applied: list[Applied]
    choices: list[Choice]  # when it couldn't tell which task: send the command again with one of these as task_id


class MyTaskOut(TaskOut):
    project_name: str
    due: date | None  # the task's date, else its milestone's, else the project deadline


class ScheduleIn(BaseModel):
    apply: bool = False


class Move(BaseModel):
    task_id: uuid.UUID
    title: str
    from_assignee_id: uuid.UUID | None
    to_assignee_id: uuid.UUID | None
    note: str
    finish: date | None
    at_risk: bool


class ScheduleOut(BaseModel):
    moves: list[Move]  # only tasks whose person changes
    predicted_finish: date | None
    at_risk: int
    applied: bool
