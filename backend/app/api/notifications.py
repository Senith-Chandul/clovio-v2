"""Your notifications. They're written by the task write path and by starting a project; this only reads them."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models import Notification, User, utcnow
from app.schemas import CountOut, NotificationsOut

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications", response_model=NotificationsOut)
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    unread = db.scalar(select(func.count()).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    items = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(30)
    ).all()
    return NotificationsOut(unread=unread, items=items)


@router.post("/notifications/read", response_model=CountOut)
def mark_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow())
    )
    db.commit()
    return CountOut(count=result.rowcount)
