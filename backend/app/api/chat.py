"""Chat: one team chat per project, and direct messages between people who share a project.

No websockets: the web app polls every few seconds, which is plenty for a team of a few dozen.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.core.access import membership
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import Conversation, ConversationKind, ConversationMember, Message, Project, ProjectMember, User, utcnow
from app.schemas import ChatOut, ChatPerson, ChatRef, ChatsOut, DirectIn, MessageIn, MessageOut

router = APIRouter(prefix="/api", tags=["chat"])

HISTORY = 200  # messages sent when a chat is opened or polled


def _chat(db: Session, chat_id: uuid.UUID, user: User) -> Conversation:
    """The chat, if this person may read it: a project chat through the project, a direct one through its members."""
    chat = db.get(Conversation, chat_id)
    if chat is not None and chat.kind == ConversationKind.project:
        membership(db, chat.project_id, user)
        return chat
    if chat is None or db.get(ConversationMember, (chat.id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found.")
    return chat


def _mark_read(db: Session, chat_id: uuid.UUID, user_id: uuid.UUID) -> None:
    seen = db.get(ConversationMember, (chat_id, user_id))
    if seen is None:  # a project chat: the row only holds what this person has read
        seen = ConversationMember(conversation_id=chat_id, user_id=user_id)
        db.add(seen)
    seen.last_read_at = utcnow()


@router.get("/chats", response_model=ChatsOut)
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your project chats and direct messages, most recent first, with what's unread, and who you can message."""
    projects = dict(db.execute(
        select(Project.id, Project.name).join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id)
    ).all())
    chats = db.scalars(select(Conversation).where(Conversation.project_id.in_(projects))).all()
    chats += db.scalars(
        select(Conversation).join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == user.id, Conversation.kind == ConversationKind.direct)
    ).all()
    other = aliased(ConversationMember)
    names = dict(db.execute(
        select(other.conversation_id, User.name).join(User, User.id == other.user_id)
        .where(other.conversation_id.in_([c.id for c in chats if c.kind == ConversationKind.direct]), other.user_id != user.id)
    ).all())

    out = []
    # shortcut: two small queries per chat; fine for a few dozen chats, use one grouped query if lists get long.
    for chat in chats:
        last = db.execute(
            select(Message.body, Message.created_at, User.name).outerjoin(User, User.id == Message.sender_id)
            .where(Message.conversation_id == chat.id).order_by(Message.created_at.desc()).limit(1)
        ).first()
        seen = db.get(ConversationMember, (chat.id, user.id))
        unread = select(func.count()).where(Message.conversation_id == chat.id, Message.sender_id != user.id)
        if seen and seen.last_read_at:
            unread = unread.where(Message.created_at > seen.last_read_at)
        out.append(ChatOut(
            id=chat.id, kind=chat.kind, project_id=chat.project_id,
            title=projects[chat.project_id] if chat.project_id else names.get(chat.id, "Someone who left"),
            last_body=last.body if last else None, last_sender=last.name if last else None,
            last_at=last.created_at if last else None, unread=db.scalar(unread),
        ))
    out.sort(key=lambda c: (c.last_at is None, -(c.last_at.timestamp() if c.last_at else 0), c.title.lower()))

    mates = select(ProjectMember.user_id).where(ProjectMember.project_id.in_(projects))
    people = db.execute(select(User.id, User.name).where(User.id.in_(mates), User.id != user.id).order_by(User.name)).all()
    return ChatsOut(chats=out, people=[ChatPerson(user_id=i, name=n) for i, n in people])


@router.post("/chats/direct", response_model=ChatRef)
def open_direct(body: DirectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The direct chat with someone you share a project with, started if there isn't one yet."""
    mine, theirs = aliased(ProjectMember), aliased(ProjectMember)
    shared = db.scalar(select(mine.project_id).join(theirs, theirs.project_id == mine.project_id)
                       .where(mine.user_id == user.id, theirs.user_id == body.user_id).limit(1))
    if body.user_id == user.id or shared is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You can message people who share a project with you.")
    a, b = aliased(ConversationMember), aliased(ConversationMember)
    existing = db.scalar(
        select(Conversation.id).join(a, a.conversation_id == Conversation.id).join(b, b.conversation_id == Conversation.id)
        .where(Conversation.kind == ConversationKind.direct, a.user_id == user.id, b.user_id == body.user_id)
        .order_by(Conversation.created_at).limit(1)
    )
    if existing:
        return ChatRef(id=existing)
    # shortcut: two people starting a chat with each other in the same instant get two chats; add a unique pair key if it happens.
    chat = Conversation(kind=ConversationKind.direct)
    db.add(chat)
    db.flush()
    db.add_all([ConversationMember(conversation_id=chat.id, user_id=user.id),
                ConversationMember(conversation_id=chat.id, user_id=body.user_id)])
    db.commit()
    return ChatRef(id=chat.id)


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
def read_messages(chat_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The latest messages, oldest first. Reading them marks the chat read, so an open chat stays read while it polls."""
    chat = _chat(db, chat_id, user)
    rows = db.execute(
        select(Message, User.name).outerjoin(User, User.id == Message.sender_id)
        .where(Message.conversation_id == chat.id).order_by(Message.created_at.desc()).limit(HISTORY)
    ).all()
    _mark_read(db, chat.id, user.id)
    db.commit()
    return [MessageOut(id=m.id, sender_id=m.sender_id, sender_name=name, body=m.body, created_at=m.created_at)
            for m, name in reversed(rows)]


@router.post("/chats/{chat_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def send_message(chat_id: uuid.UUID, body: MessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chat = _chat(db, chat_id, user)
    message = Message(conversation_id=chat.id, sender_id=user.id, body=body.body)
    db.add(message)
    _mark_read(db, chat.id, user.id)
    db.commit()
    return MessageOut(id=message.id, sender_id=user.id, sender_name=user.name, body=message.body, created_at=message.created_at)
