# Inventory Manager — classroom runbook

One page for running this in a classroom. Everything here is about *operating*
the app, not changing it.

## What it is

The stockroom system for the simulated workplace. Students check hardware out
and back in at a shared scan station using the same QR badge CLOCKIN prints,
and consumables are counted down as the class uses them. One SQLite file inside
the container is the whole application state.

## First deploy

**Step 0 — create the shared network, once, before either app.** Both stacks
expect an external Docker network called `ctec-net`, so a stack deployed
without it fails with "network ctec-net declared as external, but could not be
found" — and the CLOCKIN roster sync has nothing to talk to. In Portainer:
**Networks → Add network**, name `ctec-net`, driver `bridge`. From a shell:
`docker network create ctec-net`.

1. In Portainer: **Stacks → Add stack**, build method **Repository**,
   `https://github.com/Chavi7/inventory-manager`, ref `refs/heads/main`, compose
   `compose.yml`.
2. Under **Environment variables**, set at minimum:

   | name | value |
   |---|---|
   | `INVENTORY_SECRET_KEY` | a long random string — `python3 -c "import secrets; print(secrets.token_hex(32))"` |
   | `INVENTORY_BIND` | `0.0.0.0` so classroom PCs can reach the scan station |
   | `TZ` | your timezone, e.g. `America/New_York` — otherwise the container runs in UTC and every recorded time is hours off |

   Optional, for the one-click roster sync from CLOCKIN: `CLOCKIN_API_KEY`
   (must match the value on the CLOCKIN container) — both containers must be on
   the same `ctec-net` network.

   The app **refuses to start** if `INVENTORY_SECRET_KEY` is empty or left as
   the placeholder.
3. Deploy, open `/` — a fresh database sends you to `/setup` to create the
   teacher (admin) account. There are no default credentials.

## Check the deployment actually works

```bash
./scripts/smoke.sh http://<lab-server-ip>:5001
```

Read-only, takes a second, exits 0 if healthy. It checks the app answers, the
login and setup pages don't 500, and the scan station and badge API require a
login — the routes a blank secret used to break silently. Run it right after
deploying, and again if a period starts weird.

## The URL students use

`http://<lab-server-ip>:5001/` with `INVENTORY_BIND=0.0.0.0`. Port 5001 keeps
it clear of CLOCKIN's 5000.

**Camera scanning needs HTTPS.** Browsers only grant camera access on
`https://` or `localhost`, so over plain HTTP the scan station needs a USB
scanner (a keyboard-emulating scanner works: it types the code and presses
enter). For camera mode, put a reverse proxy with TLS in front.

## Daily use

- **Scan station** (`/scan`): student scans their CLOCKIN badge → scan the item
  label → **Check Out** (1/3/7/14 days) or **Return**. Consumables dispense
  from the same screen.
- Labels print from **Labels** — tick items, **Generate PDF**, cut out, stick on
  the gear. A printed label and the on-screen QR encode the same code.
- **History Report** for who had what, filterable to items out / overdue, and
  exportable as CSV.
- Roster: import a CLOCKIN CSV, or **Sync from CLOCKIN** if `CLOCKIN_API_KEY`
  is configured. Re-imports update by `employee_id`; nobody is duplicated.

## Backup

```bash
docker cp inventory-manager:/data/inventory.db ./inventory-$(date +%F).db
```

That file holds the roster, the asset catalog, checkouts and stock history.
Keep a copy off the server.

## When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| Pages load, `/login` or `/setup` returns 500 | `INVENTORY_SECRET_KEY` empty or placeholder | Set it and redeploy. The container now exits at boot with the reason in the logs. |
| Connection refused from a classroom PC | bound to `127.0.0.1` | Set `INVENTORY_BIND=0.0.0.0`, or reach it through the proxy |
| Camera won't start | not a secure context | HTTPS, or use a USB scanner |
| Badge scan says "isn't in the inventory roster yet" | student not imported | Roster page — import or sync |
| Badge scan says "inactive" | student deactivated by the last CLOCKIN sync | Check CLOCKIN first — the sync deactivates anyone missing there |
| "Sync from CLOCKIN" fails | API key mismatch or containers on different networks | Compare `CLOCKIN_API_KEY` on both stacks; both must join `ctec-net` |
| Item won't check out | wrong status, or the category limit is reached | Item detail shows status; Laptops are limited to 1 per student |
| Can't delete an item | it's currently checked out | Return it first — the app refuses to delete out-on-loan gear |

## End of the semester

Archive, then (only if you mean it) reset:

```bash
docker cp inventory-manager:/data/inventory.db ./inventory-archive-$(date +%F).db
```

`docker compose down -v` removes the volume and the database. **No undo** — the
archive is your recovery path.

## Running the tests (only if you're changing code)

```bash
pip install -r requirements-dev.txt
python -m pytest
```

CI runs the same suite plus `pyflakes` on every pull request.
