"""Start, check and stop the whole synthetic MahaSetu demonstration on one laptop with Docker Compose.

  python scripts/demo.py up        generate local settings, start the database, migrate and seed, start every service
  python scripts/demo.py status    probe every service's health address from this machine
  python scripts/demo.py down      stop the stack (add --wipe to discard the database and sign-in data)

This script only orchestrates: it calls scripts/bootstrap_local_db.py and `docker compose`, owns no business logic and
reads no other project's data. Needs Docker with Compose v2 and the packages in tests/requirements.txt (for the
migrations). Settings live in the Git-ignored .env.local-db; nothing here is printed that is a credential.
"""
import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
ENV_FILE = DEPLOY / ".env.local-db"
BOOTSTRAP = DEPLOY / "scripts" / "bootstrap_local_db.py"
# name -> (address as seen from the laptop, what it is)
HEALTH = {
    "scholarship portal": ("http://localhost:3000/health", "http://localhost:3000"),
    "MahaSetu website": ("http://localhost:3004/health", "http://localhost:3004"),
    "MahaSetu Core": ("http://localhost:8000/health", "http://localhost:8000"),
    "revenue API": ("http://localhost:8001/health", "SOAP 1.2"),
    "examination API": ("http://localhost:8002/health", "flat JSON"),
    "university API": ("http://localhost:8003/health", "nested JSON"),
}


def compose(*args, check=True):
    return subprocess.run(["docker", "compose", "--env-file", str(ENV_FILE), *args], cwd=DEPLOY, check=check)


def bootstrap(command):
    subprocess.run([sys.executable, str(BOOTSTRAP), command], cwd=DEPLOY, check=True)


def probe(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def status():
    ok = True
    for name, (url, note) in HEALTH.items():
        up = probe(url)
        ok &= up
        print(f"{'up  ' if up else 'DOWN'}  {name:20} {note}")
    return ok


def up():
    bootstrap("init")
    compose("--profile", "local-db", "up", "-d", "--wait", "local-db")
    bootstrap("apply")
    compose("--profile", "demo", "up", "--build", "--wait", "-d")
    deadline = time.time() + 60
    while time.time() < deadline and not status():
        time.sleep(3)
        print("--")
    print("\nOpen http://localhost:3000, register a student, create an application with a demo MahaSetu student ID "
          "(MHSTU0001 to MHSTU0005) and a ten-digit mobile number, then choose Verify with MahaSetu."
          "\nSee docs/DEMO_SCRIPT.md for the five demonstration students.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "status", "down"])
    parser.add_argument("--wipe", action="store_true", help="with down: also discard the database and sign-in volumes")
    args = parser.parse_args()
    if args.command == "up":
        up()
    elif args.command == "status":
        sys.exit(0 if status() else 1)
    else:
        compose("--profile", "demo", "down", *(["-v"] if args.wipe else []))


if __name__ == "__main__":
    main()
