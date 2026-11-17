"""Check the three running simulators with the Phase 1 fixtures over HTTP."""
import os

import requests
from jsonschema import Draft202012Validator, FormatChecker
from zeep import Client
from zeep.transports import Transport


def base(provider, port):
    return "http://127.0.0.1:" + os.environ.get(provider.upper() + "_API_PORT", str(port))


def check_rest(url, path, headers):
    contract = requests.get(url + "/openapi.json", timeout=5).json()
    schema = contract["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    endpoint = url + path.format(student_id="MHSTU0001")
    denied = requests.get(endpoint, timeout=5)
    assert denied.status_code == 401
    Draft202012Validator(contract["components"]["schemas"]["Error"]).validate(denied.json())
    response = requests.get(endpoint, headers=headers, timeout=5)
    response.raise_for_status()
    data = response.json()
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
    return data


def main():
    revenue, examination, university = base("revenue", 8001), base("examination", 8002), base("university", 8003)
    for url in (revenue, examination, university):
        health = requests.get(url+"/health", timeout=5)
        health.raise_for_status()
        assert health.json()["status"] == "ready"
    with requests.Session() as session:
        session.auth = (os.environ["REVENUE_USER"], os.environ["REVENUE_PASSWORD"])
        client = Client(revenue+"/soap/v1?wsdl", transport=Transport(session=session, timeout=5, operation_timeout=5))
        record = client.service.GetStudentCertificates(StudentID="MHSTU0001", RequestReference="docker-smoke")
        assert record.IncomeCertificate.AnnualIncomeINR == 150000 and record.CasteCertificate.Category == "DEMO-A"
    exams = check_rest(examination, "/api/v1/students/{student_id}/examination-records",
                       {"X-API-Key": os.environ["EXAMINATION_API_KEY"]})
    assert exams["ssc_total_marks"] == 480 and exams["intermediate_exam_year"] == 2025
    token = requests.post(university+"/demo/token", timeout=5,
                          auth=(os.environ["UNIVERSITY_CLIENT_ID"], os.environ["UNIVERSITY_CLIENT_SECRET"]))
    token.raise_for_status()
    academic = check_rest(university, "/api/v2/students/{student_id}/academic-records",
                          {"Authorization": "Bearer "+token.json()["access_token"]})
    assert academic["academic"]["enrolment_status"] == "ACTIVE"
    print("PASS: three HTTP readiness checks, SOAP WSDL discovery and lookup, flat and nested REST contracts")


if __name__ == "__main__":
    main()
