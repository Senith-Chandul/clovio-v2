def test_project_chat_unread_and_access(client, login):
    owner, member, stranger = login("owner@example.com", "Olu Owner"), login("member@example.com", "Mia Member"), login("x@example.com")
    pid = client.post("/api/projects", json={"name": "Gala"}, headers=owner).json()["id"]
    mia = client.post(f"/api/projects/{pid}/members", json={"email": "member@example.com"}, headers=owner).json()["user_id"]
    chats = lambda h: client.get("/api/chats", headers=h).json()  # noqa: E731

    (chat,) = chats(owner)["chats"]
    assert (chat["title"], chat["project_id"], chat["unread"], chat["last_body"]) == ("Gala", pid, 0, None)
    assert [p["name"] for p in chats(owner)["people"]] == ["Mia Member"]

    sent = client.post(f"/api/chats/{chat['id']}/messages", json={"body": "  Venue is booked  "}, headers=member)
    assert sent.status_code == 201 and sent.json()["body"] == "Venue is booked"
    assert client.post(f"/api/chats/{chat['id']}/messages", json={"body": "   "}, headers=member).status_code == 422
    (seen_by_owner,) = chats(owner)["chats"]
    assert (seen_by_owner["unread"], seen_by_owner["last_body"], seen_by_owner["last_sender"]) == (1, "Venue is booked", "Mia Member")
    assert chats(member)["chats"][0]["unread"] == 0  # your own message isn't news to you

    messages = client.get(f"/api/chats/{chat['id']}/messages", headers=owner).json()
    assert [(m["sender_name"], m["body"]) for m in messages] == [("Mia Member", "Venue is booked")]
    assert chats(owner)["chats"][0]["unread"] == 0  # reading marks it read

    # Only people in the project can read or write it, and leaving the project ends that.
    assert client.get(f"/api/chats/{chat['id']}/messages", headers=stranger).status_code == 404
    assert client.post(f"/api/chats/{chat['id']}/messages", json={"body": "hi"}, headers=stranger).status_code == 404
    client.delete(f"/api/projects/{pid}/members/{mia}", headers=owner)
    assert client.get(f"/api/chats/{chat['id']}/messages", headers=member).status_code == 404


def test_direct_messages_between_people_who_share_a_project(client, login):
    owner, member, stranger = login("owner@example.com", "Olu Owner"), login("member@example.com", "Mia Member"), login("x@example.com")
    pid = client.post("/api/projects", json={"name": "Gala"}, headers=owner).json()["id"]
    mia = client.post(f"/api/projects/{pid}/members", json={"email": "member@example.com"}, headers=owner).json()["user_id"]
    olu = client.get("/api/me", headers=owner).json()["id"]

    dm = client.post("/api/chats/direct", json={"user_id": mia}, headers=owner).json()["id"]
    assert client.post("/api/chats/direct", json={"user_id": olu}, headers=member).json()["id"] == dm  # one chat per pair
    client.post(f"/api/chats/{dm}/messages", json={"body": "Can you call the caterer?"}, headers=owner)
    direct = [c for c in client.get("/api/chats", headers=member).json()["chats"] if c["kind"] == "direct"]
    assert [(c["title"], c["unread"]) for c in direct] == [("Olu Owner", 1)]

    assert client.post("/api/chats/direct", json={"user_id": olu}, headers=stranger).status_code == 404  # no shared project
    assert client.post("/api/chats/direct", json={"user_id": olu}, headers=owner).status_code == 404  # not yourself
    assert client.get(f"/api/chats/{dm}/messages", headers=stranger).status_code == 404
