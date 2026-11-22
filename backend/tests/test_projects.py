from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import User, utcnow


def new_project(client, headers, **extra):
    body = {"name": "Launch party", "brief": "A party", "deadline": "2026-12-12", **extra}
    res = client.post("/api/projects", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_create_project_with_an_invite(client, login):
    owner = login("owner@example.com")
    project = new_project(client, owner, members=[
        {"email": "Guest@Example.com", "name": "Guest", "skills": [" Catering ", "catering", ""], "weekly_hours": 6},
        {"email": "owner@example.com"},  # yourself again: ignored
    ])
    assert project["role"] == "owner" and project["status"] == "planning"
    members = {m["email"]: m for m in project["members"]}
    assert set(members) == {"owner@example.com", "guest@example.com"}
    guest = members["guest@example.com"]
    assert guest["invited"] and guest["skills"] == ["catering"] and guest["weekly_hours"] == 6 and guest["role"] == "member"


def test_only_members_see_a_project_and_only_managers_change_it(client, login):
    owner, stranger = login("owner@example.com"), login("stranger@example.com")
    project = new_project(client, owner)
    assert client.get(f"/api/projects/{project['id']}", headers=stranger).status_code == 404
    assert client.get("/api/projects", headers=stranger).json() == []

    member = login("member@example.com")
    client.post(f"/api/projects/{project['id']}/members", json={"email": "member@example.com"}, headers=owner)
    assert client.get(f"/api/projects/{project['id']}", headers=member).json()["role"] == "member"
    assert client.patch(f"/api/projects/{project['id']}", json={"name": "Mine now"}, headers=member).status_code == 403
    assert client.delete(f"/api/projects/{project['id']}", headers=member).status_code == 403
    assert client.patch(f"/api/projects/{project['id']}", json={"status": "active"}, headers=owner).json()["status"] == "active"


def test_invitee_details_are_editable_until_they_sign_in(client, login):
    owner = login("owner@example.com")
    project = new_project(client, owner, members=[{"email": "guest@example.com"}])
    guest_id = next(m["user_id"] for m in project["members"] if m["email"] == "guest@example.com")
    url = f"/api/projects/{project['id']}/members/{guest_id}"
    assert client.patch(url, json={"skills": ["Sound"]}, headers=owner).json()["skills"] == ["sound"]

    with SessionLocal() as db:  # they sign in (with Google, say)
        db.scalar(select(User).where(User.email == "guest@example.com")).last_login_at = utcnow()
        db.commit()
    assert client.patch(url, json={"skills": ["lights"]}, headers=owner).status_code == 403
    assert client.patch(url, json={"role": "manager"}, headers=owner).json()["role"] == "manager"


def test_a_project_keeps_at_least_one_owner(client, login):
    owner = login("owner@example.com")
    project = new_project(client, owner)
    me = project["members"][0]["user_id"]
    base = f"/api/projects/{project['id']}/members/{me}"
    assert client.patch(base, json={"role": "member"}, headers=owner).status_code == 409
    assert client.delete(base, headers=owner).status_code == 403


def test_removing_someone_frees_their_open_tasks(client, login):
    owner = login("owner@example.com")
    project = new_project(client, owner, members=[{"email": "guest@example.com"}])
    guest_id = next(m["user_id"] for m in project["members"] if m["email"] == "guest@example.com")
    task = client.post(f"/api/projects/{project['id']}/tasks", json={"title": "Chairs", "assignee_id": guest_id}, headers=owner).json()
    assert client.delete(f"/api/projects/{project['id']}/members/{guest_id}", headers=owner).status_code == 204
    tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=owner).json()
    assert tasks[0]["id"] == task["id"] and tasks[0]["assignee_id"] is None


def test_project_list_counts_tasks(client, login):
    owner = login("owner@example.com")
    project = new_project(client, owner)
    for title, status in (("a", "done"), ("b", "todo")):
        client.post(f"/api/projects/{project['id']}/tasks", json={"title": title, "status": status}, headers=owner)
    [summary] = client.get("/api/projects", headers=owner).json()
    assert (summary["tasks_total"], summary["tasks_done"], summary["role"]) == (2, 1, "owner")


def test_update_my_profile(client, login):
    me = login("me@example.com")
    res = client.patch("/api/me", json={"skills": ["Design", "design"], "weekly_hours": 12}, headers=me)
    assert res.json()["skills"] == ["design"] and res.json()["weekly_hours"] == 12
