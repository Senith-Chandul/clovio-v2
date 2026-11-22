import pytest

from app.api import assist as assist_api
from app.services import assist


@pytest.fixture
def ai(monkeypatch):
    """A stand-in for the AI: returns the queued answer and records the prompt."""
    answer, prompts = {}, []

    def fake(system, user, schema):
        prompts.append(user)
        return schema.model_validate(answer)

    monkeypatch.setattr(assist, "complete_json", fake)
    return answer, prompts


@pytest.fixture
def setup(client, login):
    """Kasun's project with two open tasks, started, plus a stranger's project."""
    kasun = login("kasun@example.com", "Kasun Perera")
    pid = client.post("/api/projects", json={"name": "Launch", "deadline": "2026-12-18", "members": [{"email": "ravi@example.com", "name": "Ravi"}]}, headers=kasun).json()["id"]
    me = client.get("/api/me", headers=kasun).json()["id"]
    supplies = client.post(f"/api/projects/{pid}/tasks", json={"title": "Collect supplies delivery", "assignee_id": me}, headers=kasun).json()
    chairs = client.post(f"/api/projects/{pid}/tasks", json={"title": "Rent chairs"}, headers=kasun).json()
    client.patch(f"/api/projects/{pid}", json={"status": "active"}, headers=kasun)
    stranger = login("stranger@example.com")
    other = client.post("/api/projects", json={"name": "Secret"}, headers=stranger).json()["id"]
    client.post(f"/api/projects/{other}/tasks", json={"title": "Secret task"}, headers=stranger)
    return client, kasun, pid, supplies, chairs


def say(client, headers, **form):
    return client.post("/api/assist", data=form, headers=headers)


def test_typed_command_marks_the_task_done(setup, ai):
    client, kasun, pid, supplies, _ = setup
    answer, prompts = ai
    answer.update(actions=[{"type": "update", "task": 1, "status": "done"}])
    res = say(client, kasun, text="supplies are delivered").json()
    assert "[1] Collect supplies delivery" in prompts[0]  # their own task comes first
    assert "Secret task" not in prompts[0]  # never another project's tasks
    assert res["applied"][0]["summary"] == "marked done" and res["applied"][0]["previous"] == {"status": "todo"}  # Undo sends this back
    task = next(t for t in client.get(f"/api/projects/{pid}/tasks", headers=kasun).json() if t["id"] == supplies["id"])
    assert task["status"] == "done"
    kinds = [e["kind"] for e in client.get(f"/api/tasks/{supplies['id']}/events", headers=kasun).json()]
    assert "note" not in kinds  # a typed command without a note leaves no note


def test_voice_keeps_the_words_as_a_note(setup, ai, monkeypatch):
    client, kasun, _, supplies, _ = setup
    answer, _ = ai
    answer.update(actions=[{"type": "update", "task": 1, "status": "done"}])
    monkeypatch.setattr(assist_api, "transcribe", lambda audio, name, hint: "supplies are delivered")
    res = client.post("/api/assist", files={"audio": ("voice.webm", b"fake audio")}, headers=kasun).json()
    assert res["transcript"] == "supplies are delivered"
    notes = [e for e in client.get(f"/api/tasks/{supplies['id']}/events", headers=kasun).json() if e["kind"] == "note"]
    assert notes[0]["data"]["text"] == "supplies are delivered" and notes[0]["source"] == "voice"


def test_unsure_means_asking_not_changing(setup, ai):
    client, kasun, pid, supplies, chairs = setup
    answer, _ = ai
    answer.update(actions=[], ask={"question": "Which one?", "tasks": [1, 2, 99]})
    res = say(client, kasun, text="it's done").json()
    assert res["reply"] == "Which one?" and {c["task_id"] for c in res["choices"]} == {supplies["id"], chairs["id"]}
    assert all(t["status"] == "todo" for t in client.get(f"/api/projects/{pid}/tasks", headers=kasun).json())


def test_unknown_task_numbers_and_people_change_nothing(setup, ai):
    client, kasun, pid, _, _ = setup
    answer, _ = ai
    answer.update(actions=[{"type": "update", "task": 99, "status": "done"}, {"type": "update", "task": 2, "assignee": "Nobody"}])
    res = say(client, kasun, text="give chairs to nobody").json()
    assert res["applied"] == [] and "no one called Nobody" in res["reply"]
    assert all(t["status"] == "todo" and t["assignee_id"] is None or t["title"] != "Rent chairs" for t in client.get(f"/api/projects/{pid}/tasks", headers=kasun).json())


def test_assign_by_first_name_and_create_needs_a_project(setup, ai):
    client, kasun, pid, _, chairs = setup
    answer, _ = ai
    answer.update(actions=[{"type": "update", "task": 2, "assignee": "ravi"}, {"type": "create", "title": "Book a DJ"}])
    res = say(client, kasun, text="chairs go to Ravi and add booking a DJ").json()
    assert res["applied"][0]["summary"] == "given to Ravi" and "open a project to add tasks" in res["reply"]
    res = say(client, kasun, text="add booking a DJ", project_id=pid).json()
    assert [a["summary"] for a in res["applied"]][-1] == "added"
    assert any(t["title"] == "Book a DJ" for t in client.get(f"/api/projects/{pid}/tasks", headers=kasun).json())


def test_questions_get_answers(setup, ai):
    client, kasun, _, _, _ = setup
    answer, _ = ai
    answer.update(actions=[], answer="Two tasks are open: supplies and chairs.")
    res = say(client, kasun, text="what's left?").json()
    assert res["answered"] and res["reply"].startswith("Two tasks")


def test_my_tasks_lists_open_work_in_started_projects(setup):
    client, kasun, _, supplies, _ = setup
    mine = client.get("/api/my/tasks", headers=kasun).json()
    assert [t["id"] for t in mine] == [supplies["id"]] and mine[0]["project_name"] == "Launch" and mine[0]["due"] == "2026-12-18"
