"""Asset CRUD, item codes, and the category checkout limit."""
from helpers import add_asset


def test_a_new_asset_gets_an_auto_generated_code(admin_client, db):
    item = add_asset(admin_client, db)
    assert item["item_code"] == "DT-LAP-001"
    assert item["kind"] == "asset"
    assert item["status"] == "Available"


def test_codes_increment_per_category_and_do_not_collide(admin_client, db):
    first = add_asset(admin_client, db, name="Laptop One")
    second = add_asset(admin_client, db, name="Laptop Two")
    tool = add_asset(admin_client, db, name="Torque Driver", category="Tools")

    assert first["item_code"] == "DT-LAP-001"
    assert second["item_code"] == "DT-LAP-002"
    assert tool["item_code"] == "DT-TOOL-001"


def test_an_asset_can_be_edited(admin_client, db):
    item = add_asset(admin_client, db)
    admin_client.post(f"/item/{item['id']}/edit", data={
        "name": "Dell Latitude 5420 (repaired)",
        "category_id": item["category_id"],
        "status": "In Repair",
        "location": "Bench 2",
        "notes": "Screen replaced",
    }, follow_redirects=False)

    updated = db.execute("SELECT * FROM items WHERE id = ?", (item["id"],)).fetchone()
    assert updated["name"] == "Dell Latitude 5420 (repaired)"
    assert updated["status"] == "In Repair"
    assert updated["location"] == "Bench 2"


def test_an_available_asset_can_be_deleted(admin_client, db):
    item = add_asset(admin_client, db)
    admin_client.post(f"/item/{item['id']}/delete", follow_redirects=False)
    assert db.execute("SELECT COUNT(*) FROM items WHERE id = ?",
                      (item["id"],)).fetchone()[0] == 0


def _checkout(client, db, count=1):
    """Check out `count` laptops; returns the last API response."""
    responses = []
    for _ in range(count):
        item = add_asset(client, db, name=f"Laptop {len(responses)}")
        lookup = client.post("/api/item-lookup",
                             json={"payload": item["item_code"]}).get_json()
        responses.append(client.post("/api/checkout", json={
            "item_id": lookup["item_id"],
            "student_id": db.execute("SELECT id FROM students LIMIT 1").fetchone()["id"],
            "days": 7,
        }).get_json())
    return responses


def test_checkout_limit_blocks_a_second_laptop(admin_client, db):
    from helpers import ROSTER_CSV, import_roster
    import_roster(admin_client, ROSTER_CSV)

    responses = _checkout(admin_client, db, count=2)
    assert responses[0]["ok"] is True
    # Laptops are seeded with a checkout limit of 1.
    assert responses[1]["ok"] is False
    assert "limit" in responses[1]["message"].lower()


def test_a_checked_out_asset_cannot_be_deleted(admin_client, db):
    from helpers import ROSTER_CSV, import_roster
    import_roster(admin_client, ROSTER_CSV)
    item = add_asset(admin_client, db)
    student = db.execute("SELECT id FROM students LIMIT 1").fetchone()

    admin_client.post("/api/checkout", json={
        "item_id": item["id"], "student_id": student["id"], "days": 7})

    admin_client.post(f"/item/{item['id']}/delete", follow_redirects=False)
    still_there = db.execute("SELECT COUNT(*) FROM items WHERE id = ?",
                             (item["id"],)).fetchone()[0]
    assert still_there == 1


def test_a_checked_out_asset_keeps_its_status(admin_client, db):
    item = add_asset(admin_client, db)
    student = None
    from helpers import ROSTER_CSV, import_roster
    import_roster(admin_client, ROSTER_CSV)
    student = db.execute("SELECT id FROM students LIMIT 1").fetchone()

    admin_client.post("/api/checkout", json={
        "item_id": item["id"], "student_id": student["id"], "days": 7})

    admin_client.post(f"/item/{item['id']}/edit", data={
        "name": "Renamed",
        "category_id": item["category_id"],
        "status": "Retired-Lost",
        "location": "",
        "notes": "",
    }, follow_redirects=False)

    updated = db.execute("SELECT status FROM items WHERE id = ?",
                         (item["id"],)).fetchone()
    assert updated["status"] == "Checked Out"


def test_a_new_category_prefix_shows_up_in_new_codes(admin_client, db):
    admin_client.post("/categories", data={
        "name": "Test Equipment", "prefix": "TST", "checkout_limit": "",
    }, follow_redirects=False)
    item = add_asset(admin_client, db, name="Oscilloscope", category="Test Equipment")
    assert item["item_code"] == "DT-TST-001"


def test_category_prefix_must_be_two_to_four_letters(admin_client, db):
    admin_client.post("/categories", data={
        "name": "Bad Category", "prefix": "TOOLONG", "checkout_limit": "",
    }, follow_redirects=False)
    assert db.execute("SELECT COUNT(*) FROM categories WHERE name = 'Bad Category'"
                      ).fetchone()[0] == 0
