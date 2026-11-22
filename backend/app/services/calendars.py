"""People's calendars: when they're busy, and meetings put into the organiser's calendar.

Each person's own token reads only their own calendar. A meeting is one event in the organiser's calendar with the
attendees on it; Google (sendUpdates=all) and Outlook then send the invites themselves.
"""

import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConnectedAccount, Provider, User
from app.services import oauth

log = logging.getLogger(__name__)

GOOGLE = "https://www.googleapis.com/calendar/v3"
GRAPH = "https://graph.microsoft.com/v1.0"
BUSY_DAYS = 42  # how far ahead calendars are read
BUSY_TTL = timedelta(minutes=10)
WORK_START, WORK_END = time(9), time(17)  # the working day busy time is counted in, and meetings are suggested in

Interval = tuple[datetime, datetime]


class CalendarError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def account_for(db: Session, user_id: uuid.UUID) -> ConnectedAccount | None:
    """The person's working calendar connection, the most recently connected first."""
    return db.scalar(
        select(ConnectedAccount)
        .where(ConnectedAccount.user_id == user_id, ConnectedAccount.needs_reconnect.is_(False),
               ConnectedAccount.refresh_token.is_not(None))
        .order_by(ConnectedAccount.updated_at.desc())
    )


def _call(db: Session, account: ConnectedAccount, method: str, url: str, **kwargs) -> httpx.Response:
    token = oauth.access_token(db, account)
    headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    try:
        res = oauth.http.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as error:
        raise CalendarError(f"The calendar didn't answer: {error}") from error
    if res.status_code == 401:
        oauth._access.pop(account.id, None)  # the cached token was refused; the next call refreshes it
    if res.status_code >= 400:
        log.warning("%s calendar %s %s -> %s %s", account.provider, method, url, res.status_code, res.text[:300])
        raise CalendarError(f"The calendar refused that (HTTP {res.status_code}).", res.status_code)
    return res


def _utc(value: str) -> datetime:
    # Google sends RFC 3339; Graph sends no zone (we ask it for UTC).
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _fetch_busy(db: Session, account: ConnectedAccount, start: datetime, end: datetime) -> list[Interval]:
    if account.provider == Provider.google:
        body = _call(db, account, "POST", f"{GOOGLE}/freeBusy", json={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": "primary"}]}).json()
        primary = body.get("calendars", {}).get("primary", {})
        if primary.get("errors"):
            raise CalendarError(f"Google couldn't read the calendar: {primary['errors']}")
        return [(_utc(b["start"]), _utc(b["end"])) for b in primary.get("busy", [])]
    # Outlook: the person's own events in the window, except those shown as free.
    url = f"{GRAPH}/me/calendarView"
    params = {"startDateTime": start.isoformat(), "endDateTime": end.isoformat(), "$select": "start,end,showAs", "$top": "200"}
    out: list[Interval] = []
    for _ in range(10):  # pages of 200 events; ten is far more than six weeks of anyone's calendar
        body = _call(db, account, "GET", url, params=params, headers={"Prefer": 'outlook.timezone="UTC"'}).json()
        out += [(_utc(e["start"]["dateTime"]), _utc(e["end"]["dateTime"]))
                for e in body.get("value", []) if e.get("showAs") not in ("free", "workingElsewhere")]
        url, params = body.get("@odata.nextLink"), None
        if not url:
            break
    return out


# shortcut: busy times are cached per server process for BUSY_TTL; a meeting booked outside Clovio shows up
# within ten minutes. Move to a table if there's ever more than one worker.
_busy: dict[uuid.UUID, tuple[datetime, list[Interval]]] = {}


def forget(*user_ids: uuid.UUID) -> None:
    """Their calendars changed (a meeting booked, a calendar removed), so read them again next time."""
    for user_id in user_ids:
        _busy.pop(user_id, None)


def busy(db: Session, user: User, now: datetime | None = None) -> list[Interval] | None:
    """When the person is busy over the next BUSY_DAYS days, or None if we can't know (no calendar connected,
    or it couldn't be read). Never raises: a calendar problem mustn't break the task list."""
    now = now or datetime.now(UTC)
    cached = _busy.get(user.id)
    if cached and now - cached[0] < BUSY_TTL:
        return cached[1]
    account = account_for(db, user.id)
    if account is None:
        return None
    start = datetime.combine(now.date(), time(0), UTC)
    try:
        intervals = _merge(_fetch_busy(db, account, start, start + timedelta(days=BUSY_DAYS)))
    except (CalendarError, oauth.OAuthError, KeyError, ValueError, TypeError) as error:
        log.warning("Couldn't read %s's calendar: %s", user.email, error)
        return None
    _busy[user.id] = (now, intervals)
    return intervals


def _merge(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def busy_hours_by_day(intervals: list[Interval], tz_name: str, today: date, days: int = BUSY_DAYS) -> tuple[float, ...]:
    """Busy hours inside each day's working hours (local time), for day 0 = today onwards. Feeds the scheduler."""
    tz = zone(tz_name)
    hours = []
    for i in range(days):
        day = today + timedelta(days=i)
        lo, hi = datetime.combine(day, WORK_START, tz), datetime.combine(day, WORK_END, tz)
        seconds = sum(max(0.0, (min(end, hi) - max(start, lo)).total_seconds()) for start, end in intervals)
        hours.append(round(seconds / 3600, 2))
    return tuple(hours)


def suggest(db: Session, organiser: User, attendees: list[User], minutes: int,
            now: datetime | None = None, count: int = 5, days: int = 14) -> tuple[list[datetime], list[str]]:
    """The first times everyone with a connected calendar is free, within the organiser's working day on weekdays,
    at most two a day. Also returns the names of people whose calendars couldn't be read."""
    now = now or datetime.now(UTC)
    everyone = {u.id: u for u in [organiser, *attendees]}
    taken: list[Interval] = []
    unknown = []
    for person in everyone.values():
        times = busy(db, person, now)
        if times is None:
            unknown.append(person.name)
        else:
            taken += times
    taken = _merge(taken)
    tz = zone(organiser.timezone)
    length, step = timedelta(minutes=minutes), timedelta(minutes=30)
    # Start from the next half hour.
    earliest = (now + step).replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    slots: list[datetime] = []
    per_day: dict[date, int] = defaultdict(int)
    for i in range(days):
        day = now.astimezone(tz).date() + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        t = max(datetime.combine(day, WORK_START, tz), earliest.astimezone(tz))
        end_of_day = datetime.combine(day, WORK_END, tz)
        while t + length <= end_of_day and per_day[day] < 2 and len(slots) < count:
            if any(start < t + length and t < end for start, end in taken):
                t += step
            else:
                slots.append(t.astimezone(UTC))
                per_day[day] += 1
                t += max(length, timedelta(hours=2))  # spread the choices out
        if len(slots) >= count:
            break
    return slots, sorted(unknown)


def create_event(db: Session, account: ConnectedAccount, title: str, description: str, location: str,
                 start: datetime, end: datetime, emails: list[str]) -> str:
    """Put the meeting in the organiser's calendar with the attendees on it; returns the event's id."""
    if account.provider == Provider.google:
        body = {
            "summary": title, "description": description, "location": location,
            "start": {"dateTime": start.astimezone(UTC).isoformat()}, "end": {"dateTime": end.astimezone(UTC).isoformat()},
            "attendees": [{"email": e} for e in emails],
        }
        return _call(db, account, "POST", f"{GOOGLE}/calendars/primary/events", params={"sendUpdates": "all"}, json=body).json()["id"]
    fmt = "%Y-%m-%dT%H:%M:%S"
    body = {
        "subject": title, "body": {"contentType": "text", "content": description},
        "start": {"dateTime": start.astimezone(UTC).strftime(fmt), "timeZone": "UTC"},
        "end": {"dateTime": end.astimezone(UTC).strftime(fmt), "timeZone": "UTC"},
        "location": {"displayName": location},
        "attendees": [{"emailAddress": {"address": e}, "type": "required"} for e in emails],
    }
    return _call(db, account, "POST", f"{GRAPH}/me/events", json=body).json()["id"]


def cancel_event(db: Session, account: ConnectedAccount, event_id: str) -> None:
    """Cancel it in the organiser's calendar, which tells the attendees. Already gone counts as cancelled."""
    try:
        if account.provider == Provider.google:
            _call(db, account, "DELETE", f"{GOOGLE}/calendars/primary/events/{event_id}", params={"sendUpdates": "all"})
        else:
            _call(db, account, "POST", f"{GRAPH}/me/events/{event_id}/cancel", json={"comment": "Cancelled in Clovio."})
    except CalendarError as error:
        if error.status not in (404, 410):
            raise
