import unittest
from playwright.sync_api import sync_playwright
from test_browser import BrowserBaselineTest
from app.site import DATA
from app.capture import read_plan_page
from app.records import save_detail_entries, read_detail_entries
from app.review import review_entries
from tempfile import TemporaryDirectory
from pathlib import Path
import sqlite3

class PortalInteractionTest(BrowserBaselineTest):
    def test_revisions_do_not_combine_rights_and_checkout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.origin + 'detail?id=' + DATA['items'][0]['id'])
                page.locator('#rights').click()
                page.locator('#rights-revision').get_by_text('权益版本 1').wait_for()
                page.locator('#tier').select_option('季度卡')
                self.assertEqual(page.locator('#rights-revision').inner_text(), '')
                page.locator('#preview').click()
                page.locator('#checkout-revision').get_by_text('结算版本 2').wait_for()
                page.locator('#expire').click()
                self.assertEqual(page.locator('#checkout-revision').inner_text(), '')
                page.locator('#preview').click()
                page.locator('#checkout-revision').get_by_text('活动已失效').wait_for()
            finally:
                browser.close()
    def test_selected_business_state_reaches_receipt(self):
        initial = read_plan_page(self.origin, DATA['items'][0]['id'])
        changed = read_plan_page(self.origin, DATA['items'][0]['id'], '季度卡')
        self.assertNotEqual(initial['detail_fact']['business_key'], changed['detail_fact']['business_key'])
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'selected.sqlite3'
            save_detail_entries(database, [initial, changed])
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT count(DISTINCT business_key) FROM detail_entries').fetchone()[0], 2)
            review = review_entries(read_detail_entries(database))
            self.assertEqual(len(review), 2)
            self.assertIn('unconfirmed' if 'unconfirmed' in str(review) else 'not_observed', str(review))
    def test_distinct_source_state_transitions(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.origin + 'detail?id=' + DATA['items'][0]['id'], wait_until='domcontentloaded')
                page.locator('#tier').select_option('季度卡')
                page.locator('#rights').click()
                page.locator('#rights-revision').get_by_text('权益版本 2').wait_for()
                page.locator('#expire').click()
                self.assertEqual(page.locator('#rights-revision').inner_text(), '')
                self.assertIn('活动失效', page.locator('#offer-revision').inner_text())
            finally:
                browser.close()
    def test_entry_visit_is_append_only_and_linked(self):
        entry = read_plan_page(self.origin, DATA['items'][0]['id'])
        self.assertEqual(entry['catalog_fact']['identity'], entry['id'])
        self.assertIn('detail', entry['source'])
        self.assertIn(DATA['items'][0]['id'], entry['detail_fact']['business_key'])
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'visits.sqlite3'
            save_detail_entries(database, [entry, entry])
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM detail_entries').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT count(DISTINCT business_key) FROM detail_entries').fetchone()[0], 1)

    def test_browser_business_interaction(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.origin + "detail?id=" + DATA["items"][0]["id"], wait_until="domcontentloaded")
                page.locator('#tier').select_option('季度卡');page.locator('#rights').click();page.locator('#preview').click();self.assertIn('279 元',page.locator('#result').inner_text());page.locator('#expire').click();page.locator('#preview').click();self.assertIn('活动已失效',page.locator('#result').inner_text())
            finally:
                browser.close()
