# Dragon Technologies — Inventory Manager (Module 2)

A simulated-workplace inventory system for the CTEC classroom. Students "work
for" Dragon Technologies and manage classroom hardware as if it were a real
IT company's inventory.

This is **Module 2** of the suite. Module 1 is **CLOCKIN** (the QR time clock),
maintained separately. The two apps stay independent but share one key: the
`employee_id` on each student's CLOCKIN badge.

---

## Phase 1 — what's built

- **Login & roles** — `admin` (teacher), `manager` (student stockroom staff),
  `student` (view + scan station).
- **Categories** — each defines an ID prefix (e.g. `LAP`) and an optional
  per-category checkout limit (e.g. max 1 laptop per student).
- **Assets** — add / edit / delete, auto-generated codes like `DT-LAP-014`,
  searchable inventory list, item detail with full checkout history.
- **Scan Station** — a shared webcam PC. Scan a CLOCKIN student badge, then
  scan an asset label, then check out or return. Badge QR is parsed as JSON.
- **Checkout rules** — due dates, overdue flagging on the dashboard,
  category-based per-student limits.
- **Dashboard** — asset counts, currently-out list, overdue panel,
  low-stock panel (low-stock fills in with Phase 2).
- **Roster** — CSV import (CLOCKIN export) plus manual add.
- **History report** — printable, filterable, with CSV download.

**Phase 2 (next):** consumable supplies with quantity tracking + low-stock
alerts, and printable QR labels for asset tags.

---

## Tech stack

Python + Flask · SQLite · bcrypt · Gunicorn · Jinja2 templates · one CSS file ·
vanilla JS · self-hosted fonts and the `jsQR` library (no CDNs) ·
Docker + Compose.

---

## First-run seed data

On first launch the database is created and seeded with:

- **5 categories** — Laptops (`LAP`, limit 1), Tools (`TOOL`),
  Components (`CMP`), Peripherals (`PER`), Cables (`CBL`).
- **1 admin account** — username `admin`, password `dragon-admin`.
  **Change this password right after first login** (Users page → add a new
  admin, then delete the seeded one — or just keep it and rotate later).
- **2 demo students** — `CYB1-001` and `ITF-001`, for testing checkout
  before you import a real roster. Delete them once your roster is in.

---

## Deploying via Portainer

1. Push this folder to GitHub.
2. In Portainer: **Stacks → Add stack → Git repository**.
3. Point it at the repo; the compose file is `docker-compose.yml`.
4. **Before deploying**, edit `INVENTORY_SECRET_KEY` in the compose file to a
   long random string.
5. Deploy. The app is on host port **5001** (change in compose if needed).

The SQLite database lives in the `inventory-data` named volume, so it
survives container rebuilds.

---

## Connecting CLOCKIN badges

The CLOCKIN badge QR encodes JSON:

```json
{"school":"...","name":"...","employee_id":"...","student_id":"..."}
```

The Inventory Manager parses that JSON and uses `employee_id` (e.g. `ITF-001`)
as the lookup key. To make a badge work here, that same `employee_id` must
exist in the Inventory roster — import it via **Roster → Import CSV** (the
CLOCKIN roster export has a column named exactly `employee_id`).

No CLOCKIN code changes and no shared database file — the physical badge is
the only integration point.

---

*Built for CTEC. — Ciri*
