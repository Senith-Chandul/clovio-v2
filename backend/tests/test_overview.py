from datetime import date, timedelta


def test_overview_counts_and_bottlenecks(client, login):
    today = date.today()
    owner, member = login("owner@example.com", "Olu Owner"), login("member@example.com", "Mia Member")
    client.patch("/api/me", json={"weekly_hours": 10}, headers=member)
    deadline = (today + timedelta(days=6)).isoformat()  # one week left, so Mia has 10 free hours
    pid = client.post("/api/projects", json={"name": "Expo", "deadline": deadline}, headers=owner).json()["id"]
    mia = client.post(f"/api/projects/{pid}/members", json={"email": "member@example.com"}, headers=owner).json()["user_id"]
    stage = client.post(f"/api/projects/{pid}/milestones", json={"title": "Stage", "due_date": deadline}, headers=owner).json()["id"]

    def add(**fields):
        return client.post(f"/api/projects/{pid}/tasks", json={"milestone_id": stage, **fields}, headers=owner).json()["id"]

    finished = add(title="Book venue", estimate_hours=2, assignee_id=mia)
    add(title="Print badges", estimate_hours=30, assignee_id=mia)
    add(title="Late one", estimate_hours=2, assignee_id=mia, due_date=(today - timedelta(days=1)).isoformat())
    add(title="Nobody's", estimate_hours=6)
    client.patch(f"/api/tasks/{finished}", json={"status": "done"}, headers=member)

    o = client.get(f"/api/projects/{pid}/overview", headers=member).json()
    assert (o["tasks_total"], o["tasks_done"], o["overdue"], o["unassigned"]) == (4, 1, 1, 1)
    assert o["progress"] == 2 / 40
    assert o["on_time_rate"] == 1.0 and o["on_time_of"] == 1
    assert o["cycle_days"] is None  # went straight to done
    assert o["at_risk"] >= 1 and o["predicted_finish"] > deadline

    (person,) = [p for p in o["people"] if p["user_id"] == mia]
    assert person["open_hours"] == 32 and person["free_hours"] == 10 and person["bottleneck"] and person["overdue"] == 1
    (milestone,) = o["milestones"]
    assert (milestone["done"], milestone["total"], milestone["late"]) == (1, 4, True)
