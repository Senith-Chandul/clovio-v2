import uuid

import pytest


@pytest.fixture
def setup(client, login):
    """An owner, a member, and a project with one milestone."""
    owner, member = login("owner@example.com", "Olu Owner"), login("member@example.com", "Mia Member")
    project = client.post("/api/projects", json={"name": "Expo", "deadline": "2026-12-31"}, headers=owner).json()
    pid = project["id"]
    client.post(f"/api/projects/{pid}/members", json={"email": "member@example.com"}, headers=owner)
    milestone = client.post(f"/api/projects/{pid}/milestones", json={"title": "Prepare"}, headers=owner).json()
    return client, pid, milestone["id"], owner, member


def add(client, pid, headers, **fields):
    res = client.post(f"/api/projects/{pid}/tasks", json={"title": "Task", **fields}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_status_changes_set_times_and_history(setup):
    client, pid, _, owner, member = setup
    task = add(client, pid, member, title="Order supplies")
    started = client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"}, headers=member).json()
    assert started["started_at"] and not started["completed_at"]
    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=member).json()
    assert done["completed_at"]
    reopened = client.patch(f"/api/tasks/{task['id']}", json={"status": "todo"}, headers=member).json()
    assert reopened["completed_at"] is None

    client.post(f"/api/tasks/{task['id']}/notes", json={"text": "Supplies are delivered"}, headers=member)
    history = client.get(f"/api/tasks/{task['id']}/events", headers=owner).json()
    assert [e["kind"] for e in history] == ["note", "status", "status", "status", "created"]
    assert history[0]["actor_name"] == "Mia Member" and history[0]["data"] == {"text": "Supplies are delivered"}
    assert history[1]["data"] == {"from": "done", "to": "todo"}
    assert history[0]["created_at"].endswith(("Z", "+00:00"))  # sent with its zone, even from SQLite


def test_task_references_must_stay_in_the_project(setup, login):
    client, pid, _, owner, _ = setup
    other = client.post("/api/projects", json={"name": "Other"}, headers=owner).json()
    other_milestone = client.post(f"/api/projects/{other['id']}/milestones", json={"title": "X"}, headers=owner).json()
    stranger = login("stranger@example.com")
    stranger_id = client.get("/api/me", headers=stranger).json()["id"]
    res = client.post(f"/api/projects/{pid}/tasks", json={"title": "T", "milestone_id": other_milestone["id"]}, headers=owner)
    assert res.status_code == 422
    assert client.post(f"/api/projects/{pid}/tasks", json={"title": "T", "assignee_id": stranger_id}, headers=owner).status_code == 422
    assert client.get(f"/api/projects/{pid}/tasks", headers=stranger).status_code == 404


def test_dependency_loops_are_refused(setup):
    client, pid, _, owner, _ = setup
    first = add(client, pid, owner, title="First")
    second = add(client, pid, owner, title="Second", depends_on=[first["id"]])
    res = client.patch(f"/api/tasks/{first['id']}", json={"depends_on": [second["id"]]}, headers=owner)
    assert res.status_code == 422 and "loop" in res.json()["detail"]
    listed = {t["id"]: t for t in client.get(f"/api/projects/{pid}/tasks", headers=owner).json()}
    assert listed[second["id"]]["depends_on"] == [first["id"]]


def test_only_managers_delete(setup):
    client, pid, _, owner, member = setup
    task = add(client, pid, member)
    assert client.delete(f"/api/tasks/{task['id']}", headers=member).status_code == 403
    assert client.delete(f"/api/tasks/{task['id']}", headers=owner).status_code == 204
    assert client.get(f"/api/projects/{pid}/tasks", headers=owner).json() == []


def test_bulk_edit_is_all_or_nothing(setup):
    client, pid, _, owner, member = setup
    a, b = add(client, pid, member, title="A"), add(client, pid, member, title="B")
    ok = client.post(f"/api/projects/{pid}/tasks/bulk", json={"ids": [a["id"], b["id"]], "changes": {"status": "blocked"}}, headers=member)
    assert ok.json() == {"count": 2}
    bad = client.post(f"/api/projects/{pid}/tasks/bulk", json={"ids": [a["id"], str(uuid.uuid4())], "changes": {"status": "done"}}, headers=member)
    assert bad.status_code == 404
    statuses = {t["status"] for t in client.get(f"/api/projects/{pid}/tasks", headers=owner).json()}
    assert statuses == {"blocked"}
    assert client.post(f"/api/projects/{pid}/tasks/bulk", json={"ids": [a["id"]], "delete": True}, headers=member).status_code == 403


def test_required_fields_cant_be_cleared_and_ids_cant_be_reused(setup):
    client, pid, _, owner, _ = setup
    task_id = str(uuid.uuid4())
    task = add(client, pid, owner, id=task_id)
    assert task["id"] == task_id
    assert client.post(f"/api/projects/{pid}/tasks", json={"id": task_id, "title": "Again"}, headers=owner).status_code == 409
    assert client.patch(f"/api/tasks/{task_id}", json={"title": None}, headers=owner).status_code == 422
    cleared = client.patch(f"/api/tasks/{task_id}", json={"due_date": "2026-12-01"}, headers=owner).json()
    assert cleared["due_date"] == "2026-12-01"
    assert client.patch(f"/api/tasks/{task_id}", json={"due_date": None}, headers=owner).json()["due_date"] is None


def test_rebalance_previews_then_applies_and_respects_hand_picks(setup):
    client, pid, milestone_id, owner, member = setup
    members = {m["email"]: m["user_id"] for m in client.get(f"/api/projects/{pid}", headers=owner).json()["members"]}
    client.patch("/api/me", json={"skills": ["catering"], "weekly_hours": 20}, headers=member)
    client.patch("/api/me", json={"skills": ["design"], "weekly_hours": 20}, headers=owner)
    food = add(client, pid, owner, title="Menu", required_skills=["Catering"], estimate_hours=3, milestone_id=milestone_id)
    pinned = add(client, pid, owner, title="Poster", required_skills=["catering"], assignee_id=members["owner@example.com"])

    preview = client.post(f"/api/projects/{pid}/schedule", json={}, headers=owner).json()
    assert [(m["task_id"], m["to_assignee_id"]) for m in preview["moves"]] == [(food["id"], members["member@example.com"])]
    assert not preview["applied"]
    assert client.get(f"/api/projects/{pid}/tasks", headers=owner).json()[0]["assignee_id"] is None  # preview changed nothing

    assert client.post(f"/api/projects/{pid}/schedule", json={"apply": True}, headers=member).status_code == 403
    client.post(f"/api/projects/{pid}/schedule", json={"apply": True}, headers=owner)
    tasks = {t["id"]: t for t in client.get(f"/api/projects/{pid}/tasks", headers=owner).json()}
    assert tasks[food["id"]]["assignee_id"] == members["member@example.com"]
    assert not tasks[food["id"]]["assignee_locked"] and tasks[food["id"]]["assignment_note"].startswith("Has catering")
    assert tasks[food["id"]]["forecast_finish"] is not None
    assert tasks[pinned["id"]]["assignee_id"] == members["owner@example.com"] and tasks[pinned["id"]]["assignee_locked"]
