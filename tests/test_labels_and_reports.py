"""Printable output: QR PNGs, label PDFs, and the history report."""
from helpers import ROSTER_CSV, add_asset, import_roster


def test_item_qr_png_is_a_real_png(admin_client, db):
    item = add_asset(admin_client, db)
    response = admin_client.get(f"/item/{item['id']}/qr.png")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_item_qr_png_matches_the_shared_qr_settings(admin_client, db):
    """The label QR and the /qr.png QR must be produced the same way, or a
    printed label and a screen QR would differ for the same item."""
    import io

    import qrcode

    item = add_asset(admin_client, db)
    served = admin_client.get(f"/item/{item['id']}/qr.png").data

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=2)
    qr.add_data(item["item_code"])
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")

    assert served == buf.getvalue()


def test_missing_item_qr_is_a_404(admin_client):
    assert admin_client.get("/item/9999/qr.png").status_code == 404


def test_label_pdf_is_a_real_pdf(admin_client, db):
    item = add_asset(admin_client, db)
    response = admin_client.post("/labels/pdf", data={"item_ids": [str(item["id"])]})
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")


def test_label_pdf_handles_assets_and_consumables_together(admin_client, db):
    from helpers import add_consumable
    asset = add_asset(admin_client, db)
    consumable = add_consumable(admin_client, db)
    response = admin_client.post("/labels/pdf",
                                 data={"item_ids": [str(asset["id"]),
                                                    str(consumable["id"])]})
    assert response.status_code == 200
    assert response.data.startswith(b"%PDF")


def test_history_report_page_renders(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    item = add_asset(admin_client, db)
    student = db.execute("SELECT id FROM students LIMIT 1").fetchone()
    admin_client.post("/api/checkout", json={
        "item_id": item["id"], "student_id": student["id"], "days": 7})

    response = admin_client.get("/report/history")
    assert response.status_code == 200
    assert item["item_code"].encode() in response.data


def test_history_csv_export(admin_client, db):
    import_roster(admin_client, ROSTER_CSV)
    item = add_asset(admin_client, db)
    student = db.execute("SELECT id FROM students LIMIT 1").fetchone()
    admin_client.post("/api/checkout", json={
        "item_id": item["id"], "student_id": student["id"], "days": 7})

    response = admin_client.get("/report/history.csv")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert item["item_code"] in body
    assert "Alex Rivera" in body


def test_dashboard_renders_with_an_empty_catalog(admin_client):
    response = admin_client.get("/")
    assert response.status_code == 200
