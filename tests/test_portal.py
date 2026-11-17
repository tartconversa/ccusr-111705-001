import unittest
from playwright.sync_api import sync_playwright
from test_browser import BrowserBaselineTest
from app.site import DATA

class PortalInteractionTest(BrowserBaselineTest):
    def test_browser_business_interaction(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.origin + "detail?id=" + DATA["items"][0]["id"], wait_until="domcontentloaded")
                page.locator('#tier').select_option('季度卡');page.locator('#rights').click();page.locator('#preview').click();self.assertIn('279 元',page.locator('#result').inner_text());page.locator('#expire').click();page.locator('#preview').click();self.assertIn('活动已失效',page.locator('#result').inner_text())
            finally:
                browser.close()
