# mahasetu-deployment

Local orchestration, networking, health probes, integration tests and logs.

## Local integration

Place the six application checkouts beside this directory using their documented folder names. Copy .env.example to .env. Run `docker compose --profile foundation config`, then `docker compose --profile foundation up --build -d`, `docker compose ps`, `docker compose logs -f` and `docker compose --profile foundation down`. Each container serves a static probe. Service definitions use Compose DNS internally and loopback host bindings externally. Public deployment remains owner-managed.
