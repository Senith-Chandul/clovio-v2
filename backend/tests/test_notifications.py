def test_people_hear_about_their_work_once_the_project_starts(client, login):
    owner, member = login("owner@example.com", "Olu Owner"), login("member@example.com", "Mia Member")
    pid = client.post("/api/projects", json={"name": "Expo"}, headers=owner).json()["id"]
    mia = client.post(f"/api/projects/{pid}/members", json={"email": "member@example.com"}, headers=owner).json()["user_id"]
    inbox = lambda h: client.get("/api/notifications", headers=h).json()  # noqa: E731

    # A draft plan is quiet.
    draft = client.post(f"/api/projects/{pid}/tasks", json={"title": "Book venue", "assignee_id": mia}, headers=owner).json()
    assert inbox(member)["unread"] == 0

    # Starting sends one summary to each assignee (not the person who started it).
    client.patch(f"/api/projects/{pid}", json={"status": "active"}, headers=owner)
    started = inbox(member)
    assert started["unread"] == 1 and started["items"][0]["text"] == "Expo has started. You have 1 task."
    assert inbox(owner)["unread"] == 0

    # Being given a task tells you; doing it yourself doesn't.
    client.post(f"/api/projects/{pid}/tasks", json={"title": "Print badges", "assignee_id": mia}, headers=owner)
    assert inbox(member)["items"][0]["text"] == "Olu Owner gave you “Print badges” in Expo."
    client.post(f"/api/projects/{pid}/tasks", json={"title": "Self pick", "assignee_id": mia}, headers=member)
    assert inbox(member)["unread"] == 2

    # A blocked task tells the managers.
    client.patch(f"/api/tasks/{draft['id']}", json={"status": "blocked"}, headers=member)
    blocked = inbox(owner)
    assert blocked["unread"] == 1 and blocked["items"][0]["task_id"] == draft["id"]
    assert blocked["items"][0]["text"] == "Mia Member marked “Book venue” blocked in Expo."

    assert client.post("/api/notifications/read", headers=member).json() == {"count": 2}
    after = inbox(member)
    assert after["unread"] == 0 and all(n["read_at"] for n in after["items"])
