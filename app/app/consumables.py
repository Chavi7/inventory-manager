"""
Dragon Technologies Inventory Manager - consumables logic.

Lives separate from app.py to keep the stock-adjustment rules in one place
and easy to reason about. The only public function is `adjust_stock`, which
applies a delta to a consumable item atomically and records the adjustment.
"""
from datetime import datetime


class StockError(Exception):
    """Raised when a stock adjustment is invalid (overdraw, wrong kind, etc).

    The message is safe to show the user directly."""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def adjust_stock(conn, item_id, delta, note, adjusted_by_user_id,
                 student_id=None):
    """Apply a stock adjustment to a consumable.

    delta > 0  -> restock
    delta < 0  -> dispense
    delta == 0 is rejected (a no-op pollutes history)

    Rules enforced here, in one place, so no caller can accidentally skip them:
      * the item must exist and be kind='consumable'
      * note is required and non-blank
      * dispenses cannot drive the quantity below zero (block, not warn)

    Returns the new quantity. Raises StockError on any rule violation.

    The caller must NOT commit before calling this; this function does the
    INSERT and UPDATE in the same transaction and commits at the end.
    """
    if delta == 0:
        raise StockError("Adjustment must be a non-zero number.")

    note = (note or "").strip()
    if not note:
        raise StockError("Please include a note explaining the adjustment.")

    item = conn.execute(
        "SELECT id, kind, quantity_on_hand FROM items WHERE id = ?",
        (item_id,),
    ).fetchone()
    if item is None:
        raise StockError("That consumable no longer exists.")
    if item["kind"] != "consumable":
        raise StockError("Stock adjustments only apply to consumables.")

    current = item["quantity_on_hand"] or 0
    new_qty = current + delta
    if new_qty < 0:
        raise StockError(
            f"Cannot dispense {abs(delta)} - only {current} on hand."
        )

    # If a student was passed but the delta is positive (a restock), drop the
    # student - it doesn't make sense to attribute a restock to a student.
    if delta > 0:
        student_id = None

    conn.execute(
        "UPDATE items SET quantity_on_hand = ? WHERE id = ?",
        (new_qty, item_id),
    )
    conn.execute(
        """INSERT INTO stock_adjustments
                (item_id, delta, new_quantity, student_id, note,
                 adjusted_by, adjusted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item_id, delta, new_qty, student_id, note,
         adjusted_by_user_id, _now()),
    )
    conn.commit()
    return new_qty
