import uuid
from datetime import date, timedelta

from app.services.scheduler import Job, Person, free_hours, plan

TODAY = date(2026, 11, 23)


def person(name, skills=(), weekly=40.0, booked=0.0):
    return Person(uuid.uuid5(uuid.NAMESPACE_DNS, name), name, frozenset(skills), weekly, booked)


def job(name, hours=4.0, due=None, skills=(), depends_on=(), assignee=None, movable=True):
    return Job(uuid.uuid5(uuid.NAMESPACE_DNS, name), hours, due, frozenset(skills), frozenset(depends_on), assignee, movable)


def day(n):
    return TODAY + timedelta(days=n)


def test_best_skill_match_gets_the_task():
    ana, ben = person("ana", {"catering"}), person("ben", {"design"})
    task = job("menu", skills={"catering"})
    slot = plan([task], [ana, ben], TODAY)[task.id]
    assert slot.assignee == ana.id
    assert slot.finish == TODAY
    assert slot.note.startswith("Has catering")


def test_weekly_hours_are_a_budget_not_an_even_spread():
    ana = person("ana", weekly=10)
    first, second = job("first", hours=6), job("second", hours=6)
    slots = plan([first, second], [ana], TODAY)
    assert slots[first.id].finish == TODAY  # 6 of this week's 10 hours, today
    assert slots[second.id].finish == day(7)  # 4 hours this week, the last 2 in next week's block


def test_whoever_finishes_first_among_equals():
    busy, free = person("busy", booked=40), person("free")
    task = job("flyers", hours=4)
    assert plan([task], [busy, free], TODAY)[task.id].assignee == free.id


def test_weaker_match_wins_when_the_best_match_would_be_late():
    expert = person("expert", {"catering", "budgeting"}, booked=40)  # a full week of other work
    helper = person("helper", {"catering"})
    task = job("quotes", hours=4, due=day(2), skills={"catering", "budgeting"})
    slot = plan([task], [expert, helper], TODAY)[task.id]
    assert slot.assignee == helper.id
    assert not slot.at_risk
    assert "closer matches can't make the due date" in slot.note


def test_skill_gap_is_assigned_and_flagged():
    ana = person("ana", {"design"})
    task = job("sound check", skills={"sound engineering"})
    slot = plan([task], [ana], TODAY)[task.id]
    assert slot.assignee == ana.id
    assert slot.note.startswith("No one lists sound engineering")


def test_dependency_waits_for_its_prerequisite():
    ana = person("ana")
    first = job("book venue", hours=12)  # 8 h today, 4 h tomorrow
    second = job("send invites", hours=6, depends_on={first.id})
    slots = plan([second, first], [ana], TODAY)
    assert slots[first.id].finish == day(1)
    assert slots[second.id].finish == day(2)  # tomorrow's 4 free hours, then 2 the day after


def test_locked_task_keeps_its_person_and_uses_their_time():
    ana, ben = person("ana"), person("ben")
    locked = job("pinned", hours=8, assignee=ana.id, movable=False)
    other = job("open", hours=4)
    slots = plan([locked, other], [ana, ben], TODAY)
    assert slots[locked.id].assignee == ana.id
    assert slots[other.id].assignee == ben.id  # ana's day is taken


def test_late_task_is_at_risk():
    ana = person("ana", weekly=2)
    task = job("big job", hours=10, due=day(1))
    slot = plan([task], [ana], TODAY)[task.id]
    assert slot.at_risk
    assert "at risk: due" in slot.note


def test_same_input_same_answer():
    people = [person("ana", {"catering"}), person("ben", {"catering"}), person("cy")]
    jobs = [job(f"t{i}", hours=3, due=day(i % 4), skills={"catering"} if i % 2 else set()) for i in range(12)]
    assert plan(jobs, people, TODAY) == plan(list(jobs), list(people), TODAY)


def test_unassigned_fixed_task_and_no_people():
    task = job("orphan", movable=False)
    assert plan([task], [], TODAY)[task.id].note == "Unassigned"


def test_free_hours_respect_the_weekly_budget_daily_cap_and_other_work():
    def person(weekly, booked=0.0):
        return Person(uuid.uuid4(), "P", frozenset(), weekly, booked)

    assert free_hours(person(10), 14) == 20  # two weekly budgets
    assert free_hours(person(40), 3) == 24  # three days at the daily cap
    assert free_hours(person(10, booked=5), 7) == 5  # other projects come first
    assert free_hours(person(10), 0) == 0


def test_calendar_busy_days_push_work_later():
    today = date(2026, 11, 23)
    job = Job(uuid.uuid4(), 4.0, None, frozenset(), frozenset(), None, True)
    free = Person(uuid.uuid4(), "Free", frozenset(), 40)
    booked = Person(uuid.uuid4(), "Booked", frozenset(), 40, busy=(8.0, 6.0))  # all of Monday, most of Tuesday
    assert plan([job], [booked], today)[job.id].finish == today + timedelta(days=2)  # 2 h Tue, 2 h Wed
    assert plan([job], [booked, free], today)[job.id].assignee == free.id
    assert free_hours(booked, 3) == 0 + 2 + 8


def test_slots_say_when_work_starts():
    today = date(2026, 11, 23)
    first = Job(uuid.uuid4(), 12.0, None, frozenset(), frozenset(), None, True)
    second = Job(uuid.uuid4(), 4.0, None, frozenset(), frozenset({first.id}), None, True)
    slots = plan([first, second], [Person(uuid.uuid4(), "A", frozenset(), 40)], today)
    assert (slots[first.id].start, slots[first.id].finish) == (today, today + timedelta(days=1))  # 8 h, then 4 h
    assert slots[second.id].start == today + timedelta(days=1)  # waits for the first; the 4 h left that day
