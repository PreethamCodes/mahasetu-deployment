"""Browser checks against the seeded departments and the portals Compose profile."""
import os

import pytest
from playwright.sync_api import expect, sync_playwright

PORTALS = [
    ("revenue", 3001, "Income certificate", "Expired certificates", "EXPIRED"),
    ("examination", 3002, "SSC examination", "Missing results", "No records found."),
    ("university", 3003, "Academic registration", "Pending enrolment", "PENDING"),
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel=os.getenv("BROWSER_CHANNEL") or None)
        yield browser
        browser.close()


@pytest.mark.parametrize("name,port,heading,example,expected", PORTALS)
def test_seeded_register(browser, name, port, heading, example, expected):
    port = os.getenv(name.upper() + "_WEB_PORT", str(port))
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{port}")
        expect(page.get_by_text("Search by student ID or open a demo file")).to_be_visible()
        page.get_by_label("Student ID", exact=True).fill("mhstu0001")
        page.get_by_role("button", name="Find records").click()
        expect(page.get_by_role("heading", name=heading)).to_be_visible()
        page.get_by_role("button", name=example).click()
        expect(page.get_by_text(expected, exact=True).first).to_be_visible()
        page.get_by_label("Student ID", exact=True).fill("MHSTU9999")
        page.get_by_role("button", name="Find records").click()
        expect(page.get_by_text("No records found.", exact=True)).to_be_visible()
        page.get_by_label("Student ID", exact=True).fill("invalid")
        page.get_by_role("button", name="Find records").click()
        expect(page.get_by_role("status")).to_contain_text("Enter a student ID")
        assert page.request.get(f"http://127.0.0.1:{port}/api/lookup?id=invalid").status == 400
    finally:
        page.close()


@pytest.mark.parametrize("name,port,heading,example,expected", PORTALS)
def test_mobile_loading_and_error(browser, name, port, heading, example, expected):
    port = os.getenv(name.upper() + "_WEB_PORT", str(port))
    page = browser.new_page(viewport={"width": 375, "height": 800})
    try:
        page.goto(f"http://127.0.0.1:{port}")
        # Hold a browser request to inspect the pending UI, then inject a connection fault.
        pending = []
        page.route("**/api/lookup?*", lambda route: pending.append(route))
        page.get_by_role("button", name="Standard record").click()
        expect(page.get_by_role("button", name="Searching")).to_be_disabled()
        expect(page.get_by_role("status")).to_contain_text("Retrieving")
        page.wait_for_function("document.querySelector('section[aria-busy=true]') !== null")
        assert pending
        pending[0].abort()
        expect(page.get_by_role("status")).to_contain_text("could not be reached")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        page.close()
