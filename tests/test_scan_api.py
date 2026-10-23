"""The scan station API: badge resolution, checkout, return, dispense."""
from helpers import (ROSTER_CSV, add_asset, add_consumable, badge, import_roster)


def _student(db, employee_id="CYB1-001"):
    return db.execute("SELECT * FROM students WHERE employee_id = ?",
                      (employee_id,)).fetchone()


def test_badge_with_garbage_is_rejected(admin_client):
    response = admin_client.post("/api/badge", json={"payload": "not json at all"})
    body = response.get_json()
    assert body["ok"] is False
    assert body["reason"] == "bad_payload"


def test_badge_without_an_employee_id_is_rejected(admin_client):
    body = admin_client.post("/api/badge",
                             json={"payload": '{"school":"CTEC"}'}).get_json()
    assert body["ok"] is False
    assert body["reason"] == "no_employee_id"


def test_badge_for_an_unknown_student_is_rejected(admin_client):
    body = admin_client.post("/api/badge",
                             json={"payload": badge("NOPE-999")}).get_json()
    assert body["ok"] is False
    assert body["reason"] == "not_in_roster"


def test_badge_for_an_inactive_student_is_rejected(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    student = _student(db)
    db.execute("UPDATE students SET active = 0 WHERE id = ?", (student["id"],))
    db.commit()

    body = admin_client.post("/api/badge",
                             json={"payload": badge(student["employee_id"])}).get_json()
    assert body["ok"] is False
    assert body["reason"] == "inactive"


def test_a_real_clockin_badge_resolves_the_student(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    body = admin_client.post("/api/badge",
                             json={"payload": badge("CYB1-001")}).get_json()
    assert body["ok"] is True
    assert body["employee_id"] == "CYB1-001"
    assert body["name"] == "Alex Rivera"


def test_item_lookup_by_code(admin_client, db):
    item = add_asset(admin_client, db)
    body = admin_client.post("/api/item-lookup",
                             json={"payload": item["item_code"]}).get_json()
    assert body["ok"] is True
    assert body["kind"] == "asset"
    assert body["status"] == "Available"


def test_item_lookup_of_an_unknown_code(admin_client):
    body = admin_client.post("/api/item-lookup",
                             json={"payload": "DT-NOPE-999"}).get_json()
    assert body["ok"] is False


def test_the_full_checkout_and_return_cycle(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    item = add_asset(admin_client, db)
    student = _student(db)

    checkout = admin_client.post("/api/checkout", json={
        "item_id": item["id"], "student_id": student["id"], "days": 7}).get_json()
    assert checkout["ok"] is True
    assert db.execute("SELECT status FROM items WHERE id = ?",
                      (item["id"],)).fetchone()["status"] == "Checked Out"

    # Same item cannot go out twice.
    again = admin_client.post("/api/checkout", json={
        "item_id": item["id"], "student_id": student["id"], "days": 7}).get_json()
    assert again["ok"] is False

    returned = admin_client.post("/api/return", json={
        "item_id": item["id"], "student_id": student["id"]}).get_json()
    assert returned["ok"] is True
    assert db.execute("SELECT status FROM items WHERE id = ?",
                      (item["id"],)).fetchone()["status"] == "Available"


def test_returning_something_not_checked_out(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    item = add_asset(admin_client, db)
    student = _student(db)
    body = admin_client.post("/api/return", json={
        "item_id": item["id"], "student_id": student["id"]}).get_json()
    assert body["ok"] is False


def test_dispensing_a_consumable_at_the_station(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    item = add_consumable(admin_client, db, quantity=100)
    student = _student(db)

    body = admin_client.post("/api/consumable-dispense", json={
        "item_id": item["id"], "amount": 10, "note": "Class soldering project",
        "student_id": student["id"]}).get_json()
    assert body["ok"] is True
    assert body["new_quantity"] == 90


def test_overdrawing_a_consumable_is_blocked(admin_client, db):
    item = add_consumable(admin_client, db, quantity=5)
    body = admin_client.post("/api/consumable-dispense", json={
        "item_id": item["id"], "amount": 999, "note": "Too many"}).get_json()
    assert body["ok"] is False
    assert db.execute("SELECT quantity_on_hand FROM items WHERE id = ?",
                      (item["id"],)).fetchone()[0] == 5


def test_the_scan_api_requires_a_login(client, admin_client):
    other = client.application.test_client()
    for path in ("/api/badge", "/api/item-lookup", "/api/checkout",
                 "/api/return", "/api/consumable-dispense"):
        response = other.post(path, json={"payload": "x"})
        assert response.status_code == 302, path
