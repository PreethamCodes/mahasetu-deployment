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

## Local database

For a laptop demonstration without a hosted database, the `local-db` profile starts PostgreSQL 16 bound to loopback. A helper prepares it from the sibling repositories, so the deployment project still owns no business logic.

```powershell
pip install -r tests/requirements.txt
python scripts/bootstrap_local_db.py init
docker compose --env-file .env.local-db --profile local-db up -d --wait local-db
python scripts/bootstrap_local_db.py apply
docker compose --env-file .env.local-db --profile local-db --profile departments --profile portals --profile core up --build --wait -d
```

`init` writes the Git-ignored `.env.local-db` with generated synthetic credentials (database logins, the three provider credentials, portal demo access and Core's server credentials, including the Scholarship requester token and one-time-code demo disclosure). `apply` runs every owner's `alembic upgrade head` and `db/seed.sql`, then creates one login per schema that inherits only its own runtime role. Both commands are safe to repeat; existing credentials are kept and the seeds refresh fixture expiry dates. Add `SCHOLARSHIP_SUPABASE_URL`, `SCHOLARSHIP_PUBLISHABLE_KEY` and `SCHOLARSHIP_STORAGE_KEY` to the same file before starting `scholarship-web`, because applicant sign-in and document storage still use Supabase. Stop with `docker compose --env-file .env.local-db --profile local-db --profile departments --profile portals --profile core down`; add `-v` to discard the database volume.

The `core` profile starts MahaSetu Core (http://localhost:8000). Core needs CORE_DATABASE_URL and its credentials, which `init` generates; without them the service stops at start-up, so the foundation profile alone is no longer a no-configuration probe for Core. Core's own README lists its settings.
