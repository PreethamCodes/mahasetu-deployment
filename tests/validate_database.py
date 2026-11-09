"""Apply each owner's Alembic chain and seeds to a disposable PostgreSQL cluster."""
import os
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory

import psycopg

ROOT = Path(__file__).resolve().parents[2]
OWNERS = {"scholarship": "scholarship-portal", "revenue": "revenue-service",
          "examination": "examination-service", "university": "university-service",
          "mahasetu": "mahasetu-core"}


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def check_database(url, conn):
    conn.execute("""CREATE SCHEMA storage;
        CREATE TABLE storage.buckets(id text PRIMARY KEY, name text, public boolean);
        CREATE TABLE storage.objects(id uuid PRIMARY KEY, bucket_id text REFERENCES storage.buckets);
        ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;""")
    for schema, repo in OWNERS.items():
        env = dict(os.environ, MIGRATION_DATABASE_URL=url.replace("postgresql://", "postgresql+psycopg://"))
        for attempt in range(2):
            run(sys.executable, "-m", "alembic", "upgrade", "head", cwd=ROOT/repo, env=env)
            conn.execute((ROOT/repo/"db/seed.sql").read_text())
        assert conn.execute(f"SELECT version_num FROM {schema}.alembic_version").fetchone()[0] == schema+"_0001"
        rows = conn.execute("""SELECT relname, relrowsecurity FROM pg_class
            WHERE relnamespace=%s::regnamespace AND relkind='r' AND relname <> 'alembic_version'""", (schema,)).fetchall()
        assert rows and all(enabled for _, enabled in rows)
    for schema in OWNERS:
        for other in OWNERS:
            if other != schema:
                assert not conn.execute("SELECT has_schema_privilege(%s,%s,'USAGE')",
                                        (schema+"_runtime", other)).fetchone()[0]
    checks = [
        "SELECT count(*)=5 FROM scholarship.scholarship_applications",
        "SELECT annual_income <= 250000 FROM revenue.income_certificates WHERE student_id='MHSTU0001'",
        "SELECT annual_income > 250000 FROM revenue.income_certificates WHERE student_id='MHSTU0002'",
        "SELECT expires_on < DATE '2026-11-09' FROM revenue.income_certificates WHERE student_id='MHSTU0003'",
        "SELECT count(*)=0 FROM examination.examination_results WHERE student_id='MHSTU0004'",
        "SELECT count(*)=0 FROM university.bonafide_certificates WHERE record_ref='ENR-5'",
        "SELECT count(*)=2 FROM storage.buckets WHERE NOT public",
        "SELECT count(*)=5 FROM mahasetu.access_policies",
    ]
    for query in checks:
        assert conn.execute(query).fetchone() == (True,), query
    check_review_permissions(conn)
    print("PASS: five private schemas, repeat migrations and seeds, isolation, RLS, storage catalog and scenarios")


def check_review_permissions(conn):
    rule = json.loads((ROOT/"mahasetu-core/contracts/v1/example-rule.json").read_text())
    conn.execute("""INSERT INTO mahasetu.guideline_documents VALUES ('demo','synthetic.pdf',repeat('0',64))""")
    conn.execute("SET ROLE mahasetu_runtime")
    conn.execute("""INSERT INTO mahasetu.rule_versions(rule_id,version,scheme_id,guideline_id,definition)
                    VALUES ('demo',1,'DEMO-PMS','demo',%s::jsonb)""", (json.dumps(rule),))
    approval = """UPDATE mahasetu.rule_versions SET approval_status='APPROVED',
                  approved_by='00000000-0000-4000-8000-000000000001',approved_at=now()
                  WHERE rule_id='demo' AND version=1"""
    try:
        conn.execute(approval)
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("Runtime identity approved its own candidate")
    conn.execute("RESET ROLE")
    conn.execute("SET ROLE mahasetu_reviewer")
    assert conn.execute(approval).rowcount == 1
    assert conn.execute(approval).rowcount == 0
    conn.execute("RESET ROLE")


def main():
    with TemporaryDirectory(prefix="mahasetu-test-") as folder:
        base = Path(folder)
        data = base/"pgdata"
        password = secrets.token_hex(24)
        pwfile = base/"bootstrap-password"
        pwfile.write_text(password)
        run("initdb", "-D", data, "-U", "testowner", "-A", "scram-sha-256", "--pwfile", pwfile,
            "--encoding=UTF8", "--no-locale", stdout=subprocess.DEVNULL)
        pwfile.unlink()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        run("pg_ctl", "-D", data, "-o", f"-h 127.0.0.1 -p {port}", "-l", base/"server.log", "-w", "start")
        try:
            url = f"postgresql://testowner:{password}@127.0.0.1:{port}/postgres"
            with psycopg.connect(url, autocommit=True) as conn:
                check_database(url, conn)
        finally:
            run("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")


if __name__ == "__main__":
    main()
