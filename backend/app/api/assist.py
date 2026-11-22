"""Voice and typed commands. Plain `def`: speech-to-text and the AI block, so FastAPI runs this in its thread pool."""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.access import membership
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import EventSource, Task, User
from app.schemas import AssistOut
from app.services import assist
from app.services.llm import transcribe

router = APIRouter(prefix="/api", tags=["assist"])

MAX_AUDIO = 10 * 1024 * 1024  # a voice command is seconds long; this is far more than enough


# exclude_unset: each change's `previous` holds only the fields that changed, so Undo can send it back as is.
@router.post("/assist", response_model=AssistOut, response_model_exclude_unset=True)
def assist_command(
    text: str | None = Form(None, max_length=2000),
    audio: UploadFile | None = File(None),
    project_id: uuid.UUID | None = Form(None),
    task_id: uuid.UUID | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Say or type what changed. Without `project_id` it works across all your projects; `task_id` is the task
    on screen. The audio is transcribed and dropped, never stored."""
    if project_id:
        membership(db, project_id, user)
    if task_id:
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
        membership(db, task.project_id, user)
    if audio is not None:
        data = audio.file.read(MAX_AUDIO + 1)
        if len(data) > MAX_AUDIO:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That recording is too long. Keep voice commands short.")
        if not data:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The recording was empty. Try again.")
        hint = assist.hint(db, user, project_id)
        db.commit()  # release the connection while the audio is transcribed
        text = transcribe(data, audio.filename or "voice.webm", hint)
        if not text:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "I didn't catch anything. Try again a little closer to the mic.")
        return assist.run(db, user, text, EventSource.voice, project_id, task_id)
    if not text or not text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say or type what changed.")
    return assist.run(db, user, text, EventSource.app, project_id, task_id)
