"""End-to-end check of the whole synthetic demonstration, driven only through the public addresses a person would use.

Needs the full stack running (python scripts/demo.py up, or the same services started any other way) with Core's
OTP_DEMO_DISCLOSURE enabled and the simulated SMS inbox enabled. It uses no credentials: every step is a browser action
on the Scholarship portal or the MahaSetu website, exactly as a student would do it.

  SCHOLARSHIP_TEST_URL (default http://localhost:3000)   MAHASETU_SITE_URL (default http://localhost:3004)
  BROWSER_CHANNEL (e.g. msedge) to use an installed browser instead of Playwright's Chromium

Use localhost, not 127.0.0.1, for the portal: MahaSetu returns the applicant to the registered http://localhost:3000.
"""
import os
import re
import secrets
import urllib.request

import pytest
from playwright.sync_api import expect, sync_playwright

PORTAL = os.getenv("SCHOLARSHIP_TEST_URL", "http://localhost:3000").rstrip("/")
SITE = os.getenv("MAHASETU_SITE_URL", "http://localhost:3004").rstrip("/")
HEALTH = [PORTAL + "/health", SITE + "/health", os.getenv("CORE_URL", "http://localhost:8000").rstrip("/") + "/health",
          "http://localhost:8001/health", "http://localhost:8002/health", "http://localhost:8003/health"]
PROVIDERS = ("revenue", "examination", "university")
UNMET_INCOME = "Annual income is above the limit for this scheme."

# student -> (Core state, portal wording, plain-language reasons both the portal and the SMS must give)
STUDENTS = {
    "MHSTU0001": ("VERIFIED", "Verified", []),
    "MHSTU0002": ("FAILED_CHECK", "Not verified", [UNMET_INCOME]),
    "MHSTU0003": ("FAILED_CHECK", "Not verified", ["Income certificate has expired.", "Caste certificate has expired."]),
    "MHSTU0004": ("INSUFFICIENT_DATA", "Incomplete", ["No SSC result was found at the Examination Department."]),
    "MHSTU0005": ("PARTIAL", "Incomplete", ["Enrolment is still pending.", "No bonafide certificate was found at the University."]),
}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as driver:
        instance = driver.chromium.launch(channel=os.getenv("BROWSER_CHANNEL") or None)
        yield instance
        instance.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(25000)
    yield page
    context.close()


def test_every_service_answers_its_health_address():
    for url in HEALTH:
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.status == 200, url


def register(page):
    page.goto(PORTAL + "/register")
    page.get_by_label("Student name", exact=True).fill("Synthetic Applicant")
    page.get_by_label("Email", exact=True).fill("student." + secrets.token_hex(6) + "@example.test")
    page.get_by_label("Password", exact=True).fill(secrets.token_urlsafe(20))
    page.get_by_role("button", name="Register", exact=True).click()
    expect(page.get_by_role("heading", name="My scholarships")).to_be_visible()
    page.get_by_label("District", exact=True).fill("Demo District")
    page.get_by_role("button", name="Save profile").click()
    expect(page.get_by_role("status")).to_have_text("Profile saved.")


def apply(page, student, mobile):
    page.goto(PORTAL + "/student")
    page.get_by_role("button", name="Create application").click()
    expect(page.get_by_role("heading", name="Application details")).to_be_visible()
    url = page.url.split("?")[0]
    page.get_by_label("Institution", exact=True).fill("Synthetic College")
    page.get_by_label("Programme", exact=True).fill("Demo BSc")
    page.get_by_label("Academic reference", exact=True).fill("DEMO-ACADEMIC")
    page.get_by_label("Annual household income (INR)").fill("125000")
    page.get_by_label("MahaSetu student ID").fill(student)
    page.get_by_label("Mobile number").fill(mobile)
    page.get_by_role("button", name="Save draft").click()
    expect(page.locator(".timeline")).to_contain_text("Draft details saved")
    return url


def authorize_every_department(page):
    for provider in PROVIDERS:
        card = page.locator(f"article[data-provider={provider}]")
        card.get_by_role("button", name="Verify", exact=True).click()
        code = card.locator(".demo-code strong")
        expect(code).to_be_visible()
        card.get_by_label("Six-digit code").fill(code.inner_text())
        card.get_by_role("button", name="Confirm").click()
        expect(card).to_have_attribute("data-status", "COMPLETED")


@pytest.mark.parametrize("student", sorted(STUDENTS))
def test_student_journey_across_the_whole_stack(page, student):
    state, wording, reasons = STUDENTS[student]
    register(page)
    application = apply(page, student, "900000000" + student[-1])

    # Scholarship portal -> MahaSetu website
    page.get_by_role("button", name="Verify with MahaSetu", exact=True).click()
    expect(page).to_have_url(re.compile("^" + re.escape(SITE) + "/verify"))
    transaction = page.evaluate("fetch('/api/core/overview').then(r=>r.json()).then(o=>o.transaction_reference)")

    # MahaSetu website -> Core -> the three departments (SOAP 1.2, flat JSON with API key, nested JSON with token)
    authorize_every_department(page)
    page.get_by_role("button", name=re.compile("^Finish")).click()
    expect(page.locator("h1")).to_have_attribute("data-state", state)

    # MahaSetu website -> Scholarship portal: the outcome is read from Core, not taken from the address
    page.get_by_role("link", name=re.compile("^Return to")).click()
    expect(page).to_have_url(re.compile("^" + re.escape(application)))
    panel = page.locator("#verification")
    expect(panel.locator(".result")).to_have_attribute("data-state", state)
    expect(panel.locator(".status").first).to_have_text(wording)
    for reason in reasons:
        expect(panel.get_by_text(reason)).to_be_visible()

    # The simulated SMS inbox: one result message with the same reasons, and none when everything was verified.
    page.goto(f"{SITE}/messages?tx={transaction}")
    expect(page.locator('[data-kind="OTP"]')).to_have_count(3)
    results = page.locator('[data-kind="VERIFICATION_RESULT"]')
    expect(results).to_have_count(0 if state == "VERIFIED" else 1)
    for reason in reasons:
        expect(results.first).to_contain_text(reason)
