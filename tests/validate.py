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


def validate_layout():
    deploy = ROOT/"mahasetu-deployment"
    services = read(deploy/"compose.yaml")["services"]
    assert len(services) == 9
    targets = set()
    for service in services.values():
        context = (deploy/service["build"]["context"]).resolve()
        assert context.parent == ROOT and (context/"Dockerfile").is_file()
        assert (context/"config/health.txt").is_file() and "healthcheck" in service
        targets.add(context)
    assert len(targets) == 6
    for repo in targets | {deploy}:
        for filename in ("README.md", ".env.example", ".gitignore", "AGENTS.md"):
            assert (repo/filename).is_file()
    print("PASS: seven repository foundations and nine independent container definitions")


def payload(name):
    schema = read(CORE/(name+".schema.json"))
    return {k: v for k, v in schema.items() if k not in ("title", "$schema")}


if __name__ == "__main__":
    validate_layout()
    validate_soap()
    validate_contracts()
