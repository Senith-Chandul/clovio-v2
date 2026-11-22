"""Connected calendars (Settings) and project meetings."""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.access import membership, project_member
from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import ConnectedAccount, Meeting, Notification, Project, ProjectMember, Provider, User
from app.schemas import CalendarsOut, ConnectOut, MeetingIn, MeetingOut, SuggestIn, SuggestOut
from app.services import calendars, oauth

router = APIRouter(prefix="/api", tags=["calendars"])

NO_CALENDAR = "Connect your Google or Outlook calendar in Settings first, so the invites come from you."


@router.get("/calendars", response_model=CalendarsOut)
def my_calendars(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = db.scalars(select(ConnectedAccount).where(ConnectedAccount.user_id == user.id).order_by(ConnectedAccount.provider)).all()
    return CalendarsOut(accounts=accounts, available=[p for p in Provider if oauth.enabled(p)])


@router.post("/calendars/{provider}/connect", response_model=ConnectOut)
def connect_calendar(provider: Provider, user: User = Depends(get_current_user)):
    """A URL for the browser to visit: it can't send our bearer token on a plain navigation, so a short-lived
    ticket says who is connecting."""
    if not oauth.enabled(provider):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{oauth.LABEL[provider]} isn't set up here.")
    query = urlencode({"link": oauth.link_ticket(user.id), "next": "/settings"})
    return ConnectOut(url=f"{settings.API_URL}/api/auth/{provider}/start?{query}")


@router.delete("/calendars/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_calendar(provider: Provider, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # The person can also remove Clovio's access from their Google or Microsoft account settings.
    db.execute(delete(ConnectedAccount).where(ConnectedAccount.user_id == user.id, ConnectedAccount.provider == provider))
    calendars.forget(user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Meetings ────────────────────────────────────────────────────────────────


def _attendees(db: Session, project_id: uuid.UUID, ids: list[uuid.UUID]) -> list[User]:
    people = db.scalars(
        select(User).join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id, User.id.in_(ids))
    ).all()
    if len(people) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Everyone invited must be in this project.")
    return list(people)


def _out(db: Session, meeting: Meeting) -> MeetingOut:
    organizer = db.get(User, meeting.organizer_id) if meeting.organizer_id else None
    return MeetingOut.model_validate(meeting).model_copy(update={"organizer_name": organizer.name if organizer else None})


def _when(moment: datetime, tz_name: str) -> str:
    local = moment.astimezone(calendars.zone(tz_name))
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"


@router.get("/projects/{project_id}/meetings", response_model=list[MeetingOut])
def list_meetings(member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    """Meetings that haven't ended (and those that ended in the last day), soonest first."""
    since = datetime.now(UTC) - timedelta(days=1)
    meetings = db.scalars(
        select(Meeting).where(Meeting.project_id == member.project_id, Meeting.ends_at >= since).order_by(Meeting.starts_at)
    ).all()
    return [_out(db, m) for m in meetings]


@router.post("/projects/{project_id}/meetings/suggest", response_model=SuggestOut)
def suggest_times(body: SuggestIn, member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    organiser = db.get(User, member.user_id)
    slots, unknown = calendars.suggest(db, organiser, _attendees(db, member.project_id, body.attendee_ids), body.minutes)
    return SuggestOut(slots=slots, unknown=unknown)


@router.post("/projects/{project_id}/meetings", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
def create_meeting(body: MeetingIn, member: ProjectMember = Depends(project_member), db: Session = Depends(get_db)):
    organiser = db.get(User, member.user_id)
    account = calendars.account_for(db, organiser.id)
    if account is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_CALENDAR)
    people = _attendees(db, member.project_id, body.attendee_ids)
    emails = sorted({p.email for p in people} - {organiser.email})
    ends_at = body.starts_at + timedelta(minutes=body.minutes)
    project = db.get(Project, member.project_id)
    description = body.description or f"A meeting for {project.name}, set up in Clovio."
    try:
        event_id = calendars.create_event(db, account, body.title, description, body.location, body.starts_at, ends_at, emails)
    except oauth.OAuthError as error:
        detail = (f"Your {oauth.LABEL[account.provider]} calendar connection has expired. Reconnect it in Settings."
                  if error.revoked else f"{oauth.LABEL[account.provider]} didn't answer. Try again in a minute.")
        raise HTTPException(status.HTTP_409_CONFLICT if error.revoked else status.HTTP_502_BAD_GATEWAY, detail)
    except calendars.CalendarError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't add it to your calendar: {error}")

    meeting = Meeting(project_id=project.id, title=body.title, starts_at=body.starts_at, ends_at=ends_at,
                      location=body.location, organizer_id=organiser.id, attendee_emails=emails,
                      provider=account.provider, external_event_id=event_id)
    db.add(meeting)
    for person in people:
        if person.id != organiser.id:
            db.add(Notification(user_id=person.id, project_id=project.id, kind="meeting",
                                text=f"{organiser.name} invited you to “{body.title}” on {_when(body.starts_at, person.timezone)}."))
    # Their calendars changed, so the scheduler and suggestions re-read them.
    calendars.forget(organiser.id, *(p.id for p in people))
    db.commit()
    return _out(db, meeting)


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_meeting(meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    membership(db, meeting.project_id, user)
    # Only the organiser: cancelling goes through their calendar, and Clovio acts only on someone's own calendar.
    if meeting.organizer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the person who set up the meeting can cancel it.")
    if meeting.external_event_id:
        account = db.scalar(select(ConnectedAccount).where(ConnectedAccount.user_id == user.id, ConnectedAccount.provider == meeting.provider))
        if account is None or account.needs_reconnect:
            raise HTTPException(status.HTTP_409_CONFLICT, "Reconnect the calendar this meeting is in (Settings), then cancel it.")
        try:
            calendars.cancel_event(db, account, meeting.external_event_id)
        except (calendars.CalendarError, oauth.OAuthError) as error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't cancel it in your calendar: {error}")
    db.delete(meeting)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
