"""The wizard's AI steps. Plain `def` routes: the AI call blocks, so FastAPI runs them in its thread pool."""

import io
import uuid
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy.orm import Session

from app.core.access import membership, project_manager, require_manager
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import Milestone, Project, ProjectMember, User
from app.schemas import CountOut, MilestoneOut
from app.services import planner

router = APIRouter(prefix="/api", tags=["plan"])

MAX_UPLOAD = 10 * 1024 * 1024
MAX_BRIEF = 50_000
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class BriefOut(BaseModel):
    text: str


class QuestionsOut(BaseModel):
    questions: list[str]


class Answer(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=2000)


class OutlineIn(BaseModel):
    answers: list[Answer] = Field(default_factory=list, max_length=3)


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages[:50])


def _docx_text(data: bytes) -> str:
    # A .docx is a zip; the text is in word/document.xml. The standard library is enough to read it.
    with zipfile.ZipFile(io.BytesIO(data)) as docx:
        info = docx.getinfo("word/document.xml")
        if info.file_size > 20 * 1024 * 1024:  # a zip bomb, not a brief
            raise ValueError("document too large")
        root = ElementTree.fromstring(docx.read(info))
    return "\n".join("".join(t.text or "" for t in p.iter(f"{WORD_NS}t")) for p in root.iter(f"{WORD_NS}p"))


@router.post("/briefs/extract", response_model=BriefOut)
def extract_brief(file: UploadFile, user: User = Depends(get_current_user)):
    """The text of an attached brief, so the wizard can show exactly what the AI will read."""
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That file is over 10 MB.")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".pdf"):
            text = _pdf_text(data)
        elif name.endswith(".docx"):
            text = _docx_text(data)
        elif name.endswith((".txt", ".md")):
            text = data.decode("utf-8", errors="replace")
        else:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Attach a PDF, a Word (.docx) file or a text file.")
    except (PyPdfError, zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Couldn't read that file. Paste the brief's text instead.")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No text found in that file. If it's a scan, paste the text instead.")
    return BriefOut(text=text[:MAX_BRIEF])


@router.post("/projects/{project_id}/plan/questions", response_model=QuestionsOut)
def plan_questions(member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    return QuestionsOut(questions=planner.questions(db, db.get(Project, member.project_id)))


@router.post("/projects/{project_id}/plan/outline", response_model=list[MilestoneOut])
def plan_outline(body: OutlineIn, member: ProjectMember = Depends(project_manager), db: Session = Depends(get_db)):
    project = db.get(Project, member.project_id)
    return planner.outline(db, project, [(a.question, a.answer) for a in body.answers])


@router.post("/milestones/{milestone_id}/generate", response_model=CountOut)
def generate_tasks(milestone_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Milestone not found.")
    require_manager(membership(db, milestone.project_id, user))
    tasks = planner.milestone_tasks(db, db.get(Project, milestone.project_id), milestone, user.id)
    return CountOut(count=len(tasks))
