"""Helpers shared by the test modules."""
import io
import json


def category_id(db, name):
    row = db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    assert row is not None, f"category {name!r} was not seeded"
    return row["id"]


def add_asset(client, db, name="Dell Latitude 5420", category="Laptops",
              location="Shelf A"):
    response = client.post("/item/new", data={
        "name": name,
        "category_id": category_id(db, category),
        "location": location,
        "notes": "",
    }, follow_redirects=False)
    assert response.status_code == 302
    return db.execute("SELECT * FROM items ORDER BY id DESC LIMIT 1").fetchone()


def add_consumable(client, db, name="Resistors 220ohm", category="Components",
                   quantity=100, threshold=20):
    response = client.post("/consumables/new", data={
        "name": name,
        "category_id": category_id(db, category),
        "location": "Bin 4",
        "notes": "",
        "quantity_on_hand": str(quantity),
        "low_stock_threshold": str(threshold),
    }, follow_redirects=False)
    assert response.status_code == 302
    return db.execute("SELECT * FROM items ORDER BY id DESC LIMIT 1").fetchone()


def import_roster(client, csv_text):
    return client.post(
        "/roster/import",
        data={"csv_file": (io.BytesIO(csv_text.encode("utf-8")), "roster.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )


ROSTER_CSV = (
    "employee_id,name,student_id,section\n"
    "CYB1-001,Alex Rivera,1001,CYB1\n"
    "ITF-002,Sam Okafor,1002,ITF\n"
)


def badge(employee_id, name="Alex Rivera", student_id="1001", school="CTEC"):
    """The compact JSON a CLOCKIN badge QR carries."""
    return json.dumps({
        "school": school,
        "name": name,
        "employee_id": employee_id,
        "student_id": student_id,
    }, separators=(",", ":"))
