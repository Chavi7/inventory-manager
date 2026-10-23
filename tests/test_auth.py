"""First-run setup, login, and role enforcement."""
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def test_every_route_redirects_to_setup_before_an_admin_exists(client):
    for path in ("/", "/inventory", "/roster", "/login"):
        response = client.get(path)
        assert response.status_code == 302, path
        assert "/setup" in response.headers["Location"], path


def test_setup_creates_the_first_admin(client, db):
    response = client.post("/setup", data={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
        "confirm": ADMIN_PASSWORD,
    }, follow_redirects=False)

    assert response.status_code == 302
    row = db.execute("SELECT * FROM users").fetchone()
    assert row["username"] == ADMIN_USERNAME
    assert row["role"] == "admin"
    assert row["password_hash"] != ADMIN_PASSWORD
    assert not row["password_hash"].startswith("$2b$" + ADMIN_PASSWORD)


def test_setup_rejects_a_mismatched_confirmation(client, db):
    client.post("/setup", data={
        "username": "teacher",
        "password": "supersecret123",
        "confirm": "different-password",
    })
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_setup_is_closed_once_an_admin_exists(admin_client):
    response = admin_client.get("/setup")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_rejects_a_wrong_password(client, admin_client):
    client.get("/logout")
    response = client.post("/login",
                           data={"username": ADMIN_USERNAME, "password": "nope"},
                           follow_redirects=False)
    assert response.status_code == 200
    assert client.get("/inventory").status_code == 302


def test_login_accepts_the_right_password(admin_client):
    assert admin_client.get("/inventory").status_code == 200


def test_logout_clears_the_session(admin_client):
    admin_client.get("/logout")
    assert admin_client.get("/inventory").status_code == 302


def test_pages_require_login(client, admin_client):
    other = client.application.test_client()
    for path in ("/inventory", "/scan", "/consumables", "/report/history"):
        response = other.get(path)
        assert response.status_code == 302, path
        assert "/login" in response.headers["Location"], path


def test_a_student_cannot_reach_management_pages(admin_client, client, db):
    admin_client.post("/users", data={
        "username": "student1",
        "password": "studentpassword123",
        "role": "student",
    }, follow_redirects=False)

    other = client.application.test_client()
    other.post("/login", data={"username": "student1", "password": "studentpassword123"},
               follow_redirects=False)

    # Students may look at inventory and use the scan station...
    assert other.get("/inventory").status_code == 200
    assert other.get("/scan").status_code == 200
    # ...but not manage anything.
    for path in ("/categories", "/users", "/labels"):
        response = other.get(path)
        assert response.status_code == 302, path
        # The dashboard route is "/" in this app.
        assert response.headers["Location"] == "/", path
