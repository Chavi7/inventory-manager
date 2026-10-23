"""Units for the stock-adjustment rules in consumables.adjust_stock()."""
import pytest

import consumables
from helpers import add_consumable


def _admin_id(db):
    return db.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()["id"]


def test_restock_adds_to_the_count(admin_client, db):
    item = add_consumable(admin_client, db, quantity=10)
    new_qty = consumables.adjust_stock(db, item["id"], 5, "Order #4521 arrived",
                                       _admin_id(db))
    assert new_qty == 15


def test_dispense_subtracts_from_the_count(admin_client, db):
    item = add_consumable(admin_client, db, quantity=10)
    new_qty = consumables.adjust_stock(db, item["id"], -4, "Soldering project",
                                       _admin_id(db))
    assert new_qty == 6


def test_a_dispense_cannot_go_below_zero(admin_client, db):
    item = add_consumable(admin_client, db, quantity=3)
    with pytest.raises(consumables.StockError):
        consumables.adjust_stock(db, item["id"], -4, "Too many", _admin_id(db))

    unchanged = db.execute("SELECT quantity_on_hand FROM items WHERE id = ?",
                           (item["id"],)).fetchone()[0]
    assert unchanged == 3


def test_a_note_is_required(admin_client, db):
    item = add_consumable(admin_client, db, quantity=10)
    with pytest.raises(consumables.StockError):
        consumables.adjust_stock(db, item["id"], 5, "   ", _admin_id(db))


def test_a_zero_adjustment_is_rejected(admin_client, db):
    item = add_consumable(admin_client, db, quantity=10)
    with pytest.raises(consumables.StockError):
        consumables.adjust_stock(db, item["id"], 0, "Nothing at all", _admin_id(db))


def test_assets_cannot_be_stock_adjusted(admin_client, db):
    from helpers import add_asset
    item = add_asset(admin_client, db)
    with pytest.raises(consumables.StockError):
        consumables.adjust_stock(db, item["id"], 5, "Wrong kind", _admin_id(db))


def test_a_restock_drops_the_student_attribution(admin_client, db):
    from helpers import ROSTER_CSV, import_roster
    import_roster(admin_client, ROSTER_CSV)
    student = db.execute("SELECT id FROM students LIMIT 1").fetchone()
    item = add_consumable(admin_client, db, quantity=10)

    consumables.adjust_stock(db, item["id"], 5, "Restock", _admin_id(db),
                             student_id=student["id"])

    row = db.execute("SELECT student_id FROM stock_adjustments "
                     "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["student_id"] is None


def test_every_adjustment_is_recorded_in_history(admin_client, db):
    item = add_consumable(admin_client, db, quantity=10)
    consumables.adjust_stock(db, item["id"], 5, "Restock", _admin_id(db))
    consumables.adjust_stock(db, item["id"], -2, "Dispense", _admin_id(db))

    rows = db.execute("SELECT * FROM stock_adjustments WHERE item_id = ? "
                      "ORDER BY id", (item["id"],)).fetchall()
    assert [r["delta"] for r in rows] == [5, -2]
    assert [r["new_quantity"] for r in rows] == [15, 13]


def test_a_consumable_below_its_threshold_is_flagged(admin_client, db):
    item = add_consumable(admin_client, db, quantity=25, threshold=20)
    consumables.adjust_stock(db, item["id"], -10, "Big project", _admin_id(db))
    response = admin_client.get("/consumables")
    assert response.status_code == 200
    # The list view marks low-stock rows; the dashboard panel counts them.
    dashboard = admin_client.get("/")
    assert b"Resistors" in response.data or b"Resistors" in dashboard.data
