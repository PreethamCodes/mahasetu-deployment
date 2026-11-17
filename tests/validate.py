"""Validate the independently published contracts without starting business APIs."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator as Validator, FormatChecker
from lxml import etree
from openapi_spec_validator import validate
from zeep import Client
from zeep.wsdl.bindings.soap import Soap12Binding

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT/"mahasetu-core/contracts/v1"


def read(path):
    return json.loads(path.read_text())


def validate_soap():
    folder = ROOT/"revenue-service/contracts/v1"
    client = Client(str(folder/"revenue.wsdl"))
    assert isinstance(client.service._binding, Soap12Binding)
    schema = etree.XMLSchema(etree.parse(str(folder/"revenue.xsd")))
    env = "{http://www.w3.org/2003/05/soap-envelope}"
    for name in ("request", "response", "fault"):
        envelope = etree.parse(str(folder/(name+".xml"))).getroot()
        assert envelope.tag == env+"Envelope"
        body = envelope.find(env+"Body")[0]
        if name == "fault":
            assert body.tag == env+"Fault" and body.find(env+"Reason") is not None
            body = body.find(env+"Detail")[0]
        schema.assertValid(body)
    msg = client.create_message(client.service, "GetStudentCertificates", StudentID="MHSTU0001", RequestReference="demo")
    assert msg.tag == env+"Envelope"


def validate_contracts():
    specs = list(ROOT.glob("*/contracts/*/openapi.json"))
    assert len(specs) == 3
    for path in specs:
        spec = read(path)
        validate(spec)
        assert spec["components"]["schemas"]["Error"] == payload("error")
    for path in CORE.glob("*.schema.json"):
        Validator.check_schema(read(path))
    rule = read(CORE/"example-rule.json")
    validator = Validator(payload("rule"), format_checker=FormatChecker())
    validator.validate(rule)
    assert not validator.is_valid(dict(rule, approval_status="APPROVED"))
    assert not validator.is_valid(dict(rule, operator="EXEC"))
    assert not validator.is_valid(dict(rule, expected_value="250000"))
    canonical = read(CORE/"example-canonical.json")
    validator = Validator(payload("canonical"), format_checker=FormatChecker())
    validator.validate(canonical)
    assert not validator.is_valid(dict(canonical, retrieved_at="yesterday"))
    assert not validator.is_valid(dict(canonical, provider_id="university"))
    scope = {"authorization_reference": "10000000-0000-4000-8000-000000000001",
             "transaction_reference": "20000000-0000-4000-8000-000000000001",
             "applicant_reference": "MHSTU0001", "service_id": "DEMO-PMS",
             "provider_id": "revenue", "evidence_categories": ["income"],
             "purpose": "SCHOLARSHIP_VERIFICATION", "status": "GRANTED",
             "authorized_at": "2026-11-09T00:00:00Z", "revoked_at": None, "expires_at": None}
    auth = Validator(payload("authorization"), format_checker=FormatChecker())
    auth.validate(scope)
    assert not auth.is_valid(dict(scope, status="REVOKED"))
    assert not auth.is_valid(dict(scope, evidence_categories=[]))
    transitions = read(CORE/"states.json")
    seen = {"CREATED"}
    for _ in transitions:
        seen.update(dest for state in tuple(seen) for dest in transitions[state])
    assert seen == set(transitions)
    assert transitions["PROVIDER_ERROR"] == [] and transitions["FAILED_CHECK"] == []
    assert "FAILED_CHECK" not in transitions["AUTHENTICATION_PENDING"]
    assert set(transitions["PROCESSING"]) == {k for k, v in transitions.items() if not v}
    print("PASS: SOAP 1.2 binding and three envelopes, three OpenAPI contracts, four schemas, fixtures and state graph")


def core_validator(spec, name):
    """Validate against one component schema of the Core OpenAPI, resolving its internal references."""
    return Validator({"$ref": "#/components/schemas/" + name, "components": spec["components"]},
                     format_checker=FormatChecker())


def validate_core_flow():
    spec = read(CORE/"openapi.json")
    ops = {o["operationId"]: (path, method, o) for path, item in spec["paths"].items() for method, o in item.items()}
    assert len(ops) == sum(len(item) for item in spec["paths"].values()) == 15
    assert set(spec["components"]["securitySchemes"]) == {"Requester", "DashboardClient", "ApplicantSession"}
    expected = {"createVerificationRequest": "Requester", "getVerificationResults": "Requester",
                "exchangeLaunchReference": "DashboardClient", "listMessages": "DashboardClient",
                "getApplicantSession": "ApplicantSession", "sendDepartmentOtp": "ApplicantSession",
                "verifyDepartmentOtp": "ApplicantSession", "runDepartmentCheck": "ApplicantSession",
                "declineDepartment": "ApplicantSession", "completeApplicantSession": "ApplicantSession",
                "getApplicantResult": "ApplicantSession"}
    for op_id, scheme in expected.items():
        o = ops[op_id][2]
        assert list(o.get("security", spec["security"])[0]) == [scheme], op_id
    assert ops["getHealth"][2]["security"] == []
    # Evidence, codes and personal data never travel in a URL.
    for path, method, o in ops.values():
        for param in o.get("parameters", []):
            assert param["name"] not in {"mobile", "applicant_mobile", "income", "marks", "code", "otp"}, path
        assert "mobile" not in path
    assert spec["components"]["schemas"]["TransactionState"]["enum"] == list(read(CORE/"states.json"))

    uid = "20000000-0000-4000-8000-000000000001"
    now = "2026-11-16T10:00:00Z"
    masked = "90\u2022\u2022\u2022\u2022\u2022001"
    create = dict(service_id="DEMO-PMS", application_reference="REG-1", applicant_reference="MHSTU0001",
                  applicant_mobile="9000000001", purpose="SCHOLARSHIP_VERIFICATION",
                  requested_evidence=[dict(provider_id="revenue", evidence_categories=["income", "caste"])])
    request = core_validator(spec, "CreateVerificationRequest")
    request.validate(create)
    assert not request.is_valid({k: v for k, v in create.items() if k != "applicant_mobile"})
    for bad in ("1234567890", "90000", "+919000000001", "9000000001 "):
        assert not request.is_valid(dict(create, applicant_mobile=bad)), bad
    assert not request.is_valid(dict(create, return_url="https://example.test/"))
    created = core_validator(spec, "CreatedVerification")
    created.validate(dict(transaction_reference=uid, state="CREATED", launch_reference="a" * 43, launch_expires_at=now))
    assert not created.is_valid(dict(transaction_reference=uid, state="CREATED", launch_reference="short",
                                     launch_expires_at=now))

    check = dict(rule_id="DEMO-INCOME", rule_version=1, rule_name="Demo income ceiling", provider_id="revenue",
                 outcome="FAIL", reason_code="INCOME_ABOVE_LIMIT", evidence_reference="income-2",
                 message="Annual income on the income certificate is above the scheme limit.")
    report = dict(transaction_reference=uid, state="FAILED_CHECK", passed=5, failed=1, needs_review=0,
                  recommendation="REJECT", completed_at=now, checks=[check])
    results = core_validator(spec, "ResultReport")
    results.validate(report)
    outage = dict(check, outcome="NEEDS_REVIEW", reason_code="PROVIDER_UNAVAILABLE", rule_id=None, rule_version=None,
                  rule_name=None, evidence_reference=None, message="The department could not be reached. Try again.")
    results.validate(dict(report, state="PROVIDER_ERROR", recommendation="MANUAL_REVIEW", passed=0, failed=0,
                          needs_review=1, checks=[outage]))
    assert not results.is_valid(dict(report, checks=[{k: v for k, v in check.items() if k != "message"}]))
    assert not results.is_valid(dict(report, checks=[dict(check, outcome="TECHNICAL_FAILURE")]))

    card = dict(provider_id="revenue", display_name="Revenue Department", status="NOT_STARTED",
                authorization_required=True, detail=None, updated_at=None,
                documents=[dict(category="income", label="Income certificate",
                                description="Annual family income for the income ceiling.")])
    cards = core_validator(spec, "DepartmentCard")
    cards.validate(card)
    assert not cards.is_valid(dict(card, status="FAILED"))
    overview = dict(transaction_reference=uid, state="AUTHENTICATION_PENDING", service_id="DEMO-PMS",
                    service_name="Post-Matric Scholarship", purpose="SCHOLARSHIP_VERIFICATION",
                    mobile_masked=masked, session_expires_at=now, can_complete=True, departments=[card])
    overviews = core_validator(spec, "ApplicantOverview")
    overviews.validate(overview)
    assert not overviews.is_valid(dict(overview, mobile_masked="9000000001"))

    challenge = dict(challenge_reference=uid, provider_id="revenue", mobile_masked=masked,
                     expires_at=now, resend_after=now, attempts_allowed=3)
    otp = core_validator(spec, "OtpChallenge")
    otp.validate(challenge)
    otp.validate(dict(challenge, demo_code="048213"))
    assert not otp.is_valid(dict(challenge, demo_code="12"))
    verify = core_validator(spec, "OtpVerifyRequest")
    verify.validate(dict(challenge_reference=uid, code="048213"))
    assert not verify.is_valid(dict(challenge_reference=uid, code="12345"))
    auth = dict(authorization_reference=uid, transaction_reference=uid, applicant_reference="MHSTU0001",
                service_id="DEMO-PMS", provider_id="revenue", evidence_categories=["income"],
                purpose="SCHOLARSHIP_VERIFICATION", status="GRANTED", authorized_at=now, revoked_at=None,
                expires_at=now)
    core_validator(spec, "OtpVerified").validate(dict(department=dict(card, status="AUTHORIZED"), authorization=auth))
    core_validator(spec, "CompletionResponse").validate(dict(
        transaction_reference=uid, state="FAILED_CHECK", message_queued=True,
        return_url="http://localhost:3000/verification/return?ref=" + uid))
    message = dict(message_reference=uid, transaction_reference=uid, kind="VERIFICATION_RESULT",
                   recipient_masked=masked, status="SENT", created_at=now, sent_at=now,
                   body="MahaSetu: your scholarship verification did not pass. Reason: income above the limit.",
                   reason_codes=["INCOME_ABOVE_LIMIT"])
    listing = core_validator(spec, "MessageList")
    listing.validate(dict(messages=[message], next_cursor=None))
    assert not listing.is_valid(dict(messages=[dict(message, recipient_masked="9000000001")], next_cursor=None))
    print("PASS: Core applicant-flow contract (15 operations, three security schemes, request, report, card, "
          "OTP, completion and message examples)")


def validate_layout():
    deploy = ROOT/"mahasetu-deployment"
    services = read(deploy/"compose.yaml")["services"]
    assert len(services) == 10
    database = services["local-db"]
    assert database["image"].startswith("postgres:") and database["profiles"] == ["local-db"]
    assert all(port.startswith("127.0.0.1:") for port in database["ports"]) and "healthcheck" in database
    targets = set()
    for name, service in services.items():
        if name == "local-db":
            continue
        context = (deploy/service["build"]["context"]).resolve()
        owner = context.parent if context.name == "frontend" else context
        assert owner.parent == ROOT and (context/"Dockerfile").is_file()
        assert "healthcheck" in service
        targets.add(owner)
    assert len(targets) == 6
    for repo in targets | {deploy}:
        for filename in ("README.md", ".env.example", ".gitignore", "AGENTS.md"):
            assert (repo/filename).is_file()
    print("PASS: seven repository foundations, nine independent container definitions and the local database service")


def payload(name):
    schema = read(CORE/(name+".schema.json"))
    return {k: v for k, v in schema.items() if k not in ("title", "$schema")}


if __name__ == "__main__":
    validate_layout()
    validate_soap()
    validate_contracts()
    validate_core_flow()
