# mahasetu-deployment

Local orchestration, networking, health probes, integration tests and logs.

## Local integration

Place the six application checkouts beside this directory using their documented folder names. Copy .env.example to .env. Run `docker compose --profile foundation config`, then `docker compose --profile foundation up --build -d`, `docker compose ps`, `docker compose logs -f` and `docker compose --profile foundation down`. For the three backends alone, populate the namespaced database URLs and authentication variables in .env and run `docker compose --profile departments up --build --wait`. Each requires its own seeded schema. GET /health checks database access. The portals profile adds the three department websites. Scholarship, Dashboard and Core retain their foundation probes. Service definitions use Compose DNS internally and loopback host bindings externally. Public deployment remains owner-managed.

## Department portals

Copy .env.example to .env, configure the Phase 2 scoped database URLs and provider credentials, and enable PORTAL_DEMO_ACCESS for local synthetic-data access. The portals profile uses internal Compose DNS by default. Override REVENUE_PORTAL_BACKEND_URL, EXAMINATION_PORTAL_BACKEND_URL or UNIVERSITY_PORTAL_BACKEND_URL if a provider runs elsewhere.

```powershell
docker compose --profile portals config --quiet
docker compose --profile portals up --build --wait -d
docker compose --profile portals ps
docker compose --profile portals down
```

Open localhost:3001 (Revenue), localhost:3002 (Examination) or localhost:3003 (University). To start one pair, run `docker compose up --build --wait -d revenue-web` or substitute examination-web or university-web. For regression testing, install tests/requirements-portals.txt and a Playwright Chromium browser, then run `python -m pytest tests/test_portals.py` with the three seeded portals running. Set BROWSER_CHANNEL=msedge to use an installed Microsoft Edge instead.

## Whole demonstration on one laptop

The `demo` profile starts everything an applicant touches: the Scholarship portal, MahaSetu Core, the MahaSetu website, the three department APIs, PostgreSQL and a laptop-only sign-in and document service (`local-identity`, owned by the Scholarship project). One script does the whole sequence.

```powershell
pip install -r tests/requirements.txt
python scripts/demo.py up        # init settings, start the database, migrate and seed, start every service
python scripts/demo.py status    # probe each health address
python scripts/demo.py down      # add --wipe to discard the database and sign-in volumes
```

Then open http://localhost:3000. `docs/DEMO_SCRIPT.md` walks through the five demonstration students. To rehearse them automatically, install a Playwright browser (or set `BROWSER_CHANNEL=msedge`) and run `python -m pytest tests/test_demo.py` while the stack is up. `local-identity` is reachable only from the Scholarship portal's container and has no published port. To use a hosted Supabase project instead, replace the three `SCHOLARSHIP_SUPABASE_URL`, `SCHOLARSHIP_PUBLISHABLE_KEY` and `SCHOLARSHIP_STORAGE_KEY` values in `.env.local-db` and start the other services without `local-identity`.

## Local database

For a laptop demonstration without a hosted database, the `local-db` profile starts PostgreSQL 16 bound to loopback. A helper prepares it from the sibling repositories, so the deployment project still owns no business logic.

```powershell
pip install -r tests/requirements.txt
python scripts/bootstrap_local_db.py init
docker compose --env-file .env.local-db --profile local-db up -d --wait local-db
python scripts/bootstrap_local_db.py apply
docker compose --env-file .env.local-db --profile local-db --profile departments --profile portals --profile core up --build --wait -d
```

`init` writes the Git-ignored `.env.local-db` with generated synthetic credentials (database logins, the three provider credentials, portal demo access and Core's server credentials, including the Scholarship requester token and one-time-code demo disclosure). `apply` runs every owner's `alembic upgrade head` and `db/seed.sql`, then creates one login per schema that inherits only its own runtime role. Both commands are safe to repeat; existing credentials are kept and the seeds refresh fixture expiry dates. The same file defaults applicant sign-in and document storage to the laptop-only `local-identity` service (profile `local-identity`); replace the three `SCHOLARSHIP_` Supabase settings in it to use a hosted project. Stop with `docker compose --env-file .env.local-db --profile local-db --profile departments --profile portals --profile core down`; add `-v` to discard the database volume.

The `core` profile starts MahaSetu Core (http://localhost:8000) and the MahaSetu website (http://localhost:3004, service `dashboard-web`, which reaches Core as http://core-api:8000 with DASHBOARD_CLIENT_TOKEN). Core needs CORE_DATABASE_URL and its credentials, which `init` generates; without them the service stops at start-up, so the foundation profile alone is no longer a no-configuration probe for Core. Core's own README lists its settings.
