"""The whole schema. Every table is reached through a project, so workspaces can be added later as one
table and one projects column. Progress, milestone status and metrics are derived on read, not stored."""

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(cls: type[enum.Enum]) -> Enum:
    # Stored as plain text, not a Postgres enum type, so adding a value needs no migration.
    return Enum(cls, native_enum=False, length=20)


class Role(enum.StrEnum):
    owner = "owner"
    manager = "manager"
    member = "member"


class ProjectStatus(enum.StrEnum):
    planning = "planning"  # the wizard is still building the plan; nobody is notified yet
    active = "active"
    done = "done"
    archived = "archived"


class TaskStatus(enum.StrEnum):
    # The one status list, used as is by the API, the frontend and the AI.
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class Provider(enum.StrEnum):
    google = "google"
    microsoft = "microsoft"


class EventKind(enum.StrEnum):
    created = "created"
    edited = "edited"
    status = "status"
    assigned = "assigned"
    note = "note"
    deleted = "deleted"


class EventSource(enum.StrEnum):
    app = "app"
    ai = "ai"
    voice = "voice"


class ConversationKind(enum.StrEnum):
    project = "project"
    direct = "direct"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(unique=True)  # always lowercased
    name: Mapped[str]
    password_hash: Mapped[str | None]  # dev and demo accounts only
    weekly_hours: Mapped[float] = mapped_column(default=10)  # time they can give, across all projects
    timezone: Mapped[str] = mapped_column(default="UTC")
    skills: Mapped[list[str]] = mapped_column(default=list)  # free text, lowercased
    # An invite creates the user, so work can be assigned before they sign in. None: not signed in yet.
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[Provider] = mapped_column(str_enum(Provider))
    subject: Mapped[str]  # the ID token's sub: the provider's stable id for this person
    email: Mapped[str]
    refresh_token: Mapped[str | None]  # Fernet-encrypted, never stored in plain text
    scopes: Mapped[list[str]] = mapped_column(default=list)
    needs_reconnect: Mapped[bool] = mapped_column(default=False)  # the refresh token stopped working
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    brief: Mapped[str] = mapped_column(default="")  # what the AI plans from, plus answers to its questions
    deadline: Mapped[date | None]  # the event date, or when the project must be done
    status: Mapped[ProjectStatus] = mapped_column(str_enum(ProjectStatus), default=ProjectStatus.planning)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[Role] = mapped_column(str_enum(Role), default=Role.member)
    joined_at: Mapped[datetime] = mapped_column(default=utcnow)


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    position: Mapped[int] = mapped_column(default=0)
    due_date: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_assignee_status", "assignee_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # Deleting a milestone keeps its tasks.
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("milestones.id", ondelete="SET NULL"), index=True)
    title: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus), default=TaskStatus.todo)
    estimate_hours: Mapped[float | None]
    due_date: Mapped[date | None]
    required_skills: Mapped[list[str]] = mapped_column(default=list)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assignee_locked: Mapped[bool] = mapped_column(default=False)  # a person chose the assignee; rebalancing keeps it
    assignment_note: Mapped[str] = mapped_column(default="")  # why this person, or why the task is at risk
    position: Mapped[float] = mapped_column(default=0)  # order within a list or board column
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True, index=True)


class TaskEvent(Base):
    """Task history, comments (kind=note) and voice transcripts, in one log. Feeds cycle time and undo."""

    __tablename__ = "task_events"
    __table_args__ = (
        Index("ix_task_events_task_created", "task_id", "created_at"),
        Index("ix_task_events_project_created", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))  # kept after a delete
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[EventKind] = mapped_column(str_enum(EventKind))
    source: Mapped[EventSource] = mapped_column(str_enum(EventSource), default=EventSource.app)
    data: Mapped[dict] = mapped_column(default=dict)  # e.g. {"from": "todo", "to": "done"} or {"text": "..."}
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    location: Mapped[str] = mapped_column(default="")
    organizer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attendee_emails: Mapped[list[str]] = mapped_column(default=list)
    # The event in the organiser's calendar, so it can be updated or cancelled.
    provider: Mapped[Provider | None] = mapped_column(str_enum(Provider))
    external_event_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    kind: Mapped[str]
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    read_at: Mapped[datetime | None]


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)  # None: a direct message
    kind: Mapped[ConversationKind] = mapped_column(str_enum(ConversationKind))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    last_read_at: Mapped[datetime | None]


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
