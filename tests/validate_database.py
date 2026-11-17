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
        assert conn.execute(f"SELECT version_num FROM {schema}.alembic_version").fetchone()[0] == (schema+{"scholarship": "_0004", "mahasetu": "_0002"}.get(schema, "_0001"))
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
        # Verification inputs and fixture dates that must outlast the demonstration period.
        "SELECT count(*)=5 FROM scholarship.scholarship_applications WHERE mahasetu_student_id=student_ref"
        " AND applicant_mobile ~ '^[6-9][0-9]{9}$'",
        "SELECT bool_and(expires_on >= DATE '2030-12-31') FROM revenue.income_certificates WHERE status='VALID'",
        "SELECT bool_and(expires_on >= DATE '2030-12-31') FROM revenue.caste_certificates WHERE status='VALID'",
        "SELECT bool_and(valid_until >= DATE '2030-12-31') FROM university.bonafide_certificates",
        # Seeded, pre-approved demonstration rules and department document labels used by the applicant flow.
        "SELECT count(*)=8 FROM mahasetu.rule_versions WHERE scheme_id='DEMO-PMS' AND approval_status='APPROVED'"
        " AND rule_id LIKE 'DEMO-%' AND definition->>'approval_status'='APPROVED'",
        "SELECT count(*)=5 FROM mahasetu.evidence_categories",
        "SELECT count(*)=1 FROM mahasetu.registered_services WHERE service_id='DEMO-PMS' AND display_name <> service_id",
    ]
    for query in checks:
        assert conn.execute(query).fetchone() == (True,), query
    check_verification_inputs(conn)
    check_review_permissions(conn)
    check_applicant_flow_tables(conn)
    check_verification_records(conn)
    print("PASS: five private schemas, repeat migrations and seeds, isolation, RLS, storage catalog and scenarios")


def check_verification_inputs(conn):
    for column, value in (("applicant_mobile", "1234567890"), ("applicant_mobile", "90000"),
                          ("mahasetu_student_id", "student-1"), ("mahasetu_student_id", "MHSTU12")):
        try:
            conn.execute(f"UPDATE scholarship.scholarship_applications SET {column}=%s WHERE student_ref='MHSTU0001'", (value,))
        except psycopg.errors.CheckViolation:
            continue
        raise AssertionError(f"Accepted invalid {column}: {value}")


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


def check_verification_records(conn):
    """The portal's record of MahaSetu verification attempts keeps its invariants in the database."""
    app = "10000000-0000-4000-8000-000000000001"
    insert = "INSERT INTO scholarship.verification_transactions (transaction_ref, application_id, mahasetu_student_id) VALUES (gen_random_uuid(), %s, 'MHSTU0001')"
    conn.execute(insert, (app,))
    for statement, params in ((insert, (app,)),  # a second attempt waiting for the applicant
                              ("UPDATE scholarship.scholarship_applications SET verification_status='MAYBE' WHERE id=%s", (app,)),
                              ("UPDATE scholarship.verification_transactions SET status='COMPLETED' WHERE application_id=%s", (app,))):  # no outcome
        try:
            conn.execute(statement, params)
        except (psycopg.errors.UniqueViolation, psycopg.errors.CheckViolation):
            continue
        raise AssertionError("Verification record constraint did not hold: " + statement[:60])
    conn.execute("UPDATE scholarship.scholarship_applications SET verification_status='VERIFIED' WHERE id=%s", (app,))


def check_applicant_flow_tables(conn):
    """Core's runtime role can use the applicant-flow tables but the database still enforces the rules."""
    conn.execute("SET ROLE mahasetu_runtime")
    request = conn.execute("""INSERT INTO mahasetu.verification_requests (applicant_ref, application_ref, service_id, purpose,
        requested_evidence, idempotency_key, payload_digest, state, applicant_mobile)
        VALUES ('MHSTU0001','APP-DB-CHECK','DEMO-PMS','SCHOLARSHIP_VERIFICATION','[]','db-check','x','CREATED','9000000001')
        RETURNING id""").fetchone()[0]
    insert = """INSERT INTO mahasetu.message_outbox (request_id, kind, recipient_mobile, body)
        VALUES (%s, 'VERIFICATION_RESULT', '9000000001', 'b')"""
    conn.execute(insert, (request,))
    for statement, params in ((insert, (request,)),  # a second result message for one transaction
                              ("""INSERT INTO mahasetu.message_outbox (request_id, kind, recipient_mobile, body)
                                  VALUES (%s, 'OTP', '123', 'b')""", (request,)),  # malformed recipient
                              ("""INSERT INTO mahasetu.otp_challenges (request_id, provider_id, code_hash, status, expires_at,
                                  resend_after) VALUES (%s, 'revenue', 'h', 'VERIFIED', now(), now())""", (request,))):
        try:
            conn.execute(statement, params)
        except (psycopg.errors.UniqueViolation, psycopg.errors.CheckViolation):
            continue
        raise AssertionError("Applicant-flow constraint did not hold: " + statement.split("(")[0])
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
