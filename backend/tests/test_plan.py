import io
import zipfile
from datetime import date, timedelta

import pytest

from app.services import planner

DEADLINE = date.today() + timedelta(days=30)


@pytest.fixture
def ai(monkeypatch):
    """A stand-in for the AI: answers by the shape asked for, and records the prompts."""
    answers, prompts = {}, []

    def fake(system, user, schema):
        prompts.append(user)
        return schema.model_validate(answers[schema.__name__])

    monkeypatch.setattr(planner, "complete_json", fake)
    return answers, prompts


@pytest.fixture
def project(client, login):
    owner = login("owner@example.com")
    body = {"brief": "A product launch party for 80 guests", "deadline": DEADLINE.isoformat(), "members": [{"email": "chef@example.com", "skills": ["catering"]}]}
    return client.post("/api/projects", json=body, headers=owner).json(), owner


def test_questions_are_trimmed_to_three(client, project, ai):
    answers, _ = ai
    answers["AIQuestions"] = {"questions": [" How many guests? ", "", "Is the venue booked?", "Budget?", "Theme?"]}
    proj, owner = project
    res = client.post(f"/api/projects/{proj['id']}/plan/questions", headers=owner)
    assert res.json() == {"questions": ["How many guests?", "Is the venue booked?", "Budget?"]}


def test_outline_names_the_project_and_keeps_dates_in_order(client, project, ai):
    answers, prompts = ai
    answers["AIOutline"] = {"name": "Launch party", "milestones": [
        {"title": "Venue and Core Services Secured", "due_date": (DEADLINE + timedelta(days=9)).isoformat()},  # after the deadline
        {"title": "Guests", "due_date": (date.today() - timedelta(days=3)).isoformat()},  # in the past
        {"title": "  "},
    ]}
    proj, owner = project
    body = {"answers": [{"question": "How many guests?", "answer": "About 80"}]}
    milestones = client.post(f"/api/projects/{proj['id']}/plan/outline", json=body, headers=owner).json()
    assert [m["title"] for m in milestones] == ["Venue and core services secured", "Guests"]  # sentence case
    assert milestones[0]["due_date"] == DEADLINE.isoformat()
    assert milestones[1]["due_date"] == DEADLINE.isoformat()  # never before the one it follows
    assert "About 80" in prompts[0] and "chef" in prompts[0]
    saved = client.get(f"/api/projects/{proj['id']}", headers=owner).json()
    assert saved["name"] == "Launch party" and "About 80" in saved["brief"]
    assert client.post(f"/api/projects/{proj['id']}/plan/outline", json={}, headers=owner).status_code == 409


def test_milestone_tasks_are_saved_with_links_and_clamped_dates(client, project, ai):
    answers, prompts = ai
    answers["AIOutline"] = {"milestones": [{"title": "Food", "due_date": DEADLINE.isoformat()}]}
    proj, owner = project
    [milestone] = client.post(f"/api/projects/{proj['id']}/plan/outline", json={}, headers=owner).json()
    answers["AITasks"] = {"tasks": [
        {"title": "Pick a caterer", "estimate_hours": 3, "required_skills": ["Catering"], "due_date": "2000-01-01"},
        {"title": "Agree the menu", "estimate_hours": 0.1, "depends_on": ["pick a caterer", "unknown task", "Agree the menu"]},
        {"title": "   "},  # skipped
    ]}
    assert client.post(f"/api/milestones/{milestone['id']}/generate", headers=owner).json() == {"count": 2}
    assert "catering" in prompts[-1]  # the team's skill words are offered to the AI

    tasks = {t["title"]: t for t in client.get(f"/api/projects/{proj['id']}/tasks", headers=owner).json()}
    assert tasks["Pick a caterer"]["due_date"] is None  # the AI's dates are ignored; the milestone's applies
    assert tasks["Pick a caterer"]["required_skills"] == ["catering"]
    assert tasks["Agree the menu"]["estimate_hours"] == 0.5
    assert tasks["Agree the menu"]["depends_on"] == [tasks["Pick a caterer"]["id"]]
    assert all(t["assignee_id"] is None for t in tasks.values())  # the AI never assigns
    assert client.post(f"/api/milestones/{milestone['id']}/generate", headers=owner).status_code == 409


def test_sentence_case_only_touches_title_case():
    assert planner._sentence_case("Book AV and Stage Crew") == "Book AV and stage crew"
    assert planner._sentence_case("Venue and suppliers booked") == "Venue and suppliers booked"
    assert planner._sentence_case("Run-of-show ready") == "Run-of-show ready"


def test_without_an_ai_key_it_says_so(client, project):
    proj, owner = project
    res = client.post(f"/api/projects/{proj['id']}/plan/questions", headers=owner)
    assert res.status_code == 503 and "GROQ_API_KEY" in res.json()["detail"]


def test_extract_brief_from_text_and_word(client, login):
    headers = login("me@example.com")
    txt = client.post("/api/briefs/extract", files={"file": ("brief.txt", b"Gala dinner\n\n200 guests  \n")}, headers=headers)
    assert txt.json() == {"text": "Gala dinner\n\n200 guests"}

    docx = io.BytesIO()
    body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' \
           '<w:p><w:r><w:t>Gala </w:t></w:r><w:r><w:t>dinner</w:t></w:r></w:p><w:p><w:r><w:t>200 guests</w:t></w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", body)
    res = client.post("/api/briefs/extract", files={"file": ("brief.docx", docx.getvalue())}, headers=headers)
    assert res.json() == {"text": "Gala dinner\n200 guests"}

    assert client.post("/api/briefs/extract", files={"file": ("brief.exe", b"MZ")}, headers=headers).status_code == 415
    assert client.post("/api/briefs/extract", files={"file": ("bad.pdf", b"not a pdf")}, headers=headers).status_code == 422
