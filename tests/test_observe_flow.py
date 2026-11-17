import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app.site import DATA, start_server
from app.capture import observe_plan
from app.records import save_observations, read_observations
from app.review import review_observations


class ObserveFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server()
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.plan_id = DATA['items'][0]['id']

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    def test_each_tier_is_an_independent_complete_round(self):
        result = observe_plan(self.origin, self.plan_id)
        self.assertEqual([round_['tier'] for round_ in result['rounds']], ['月卡', '季度卡'])
        self.assertEqual(result['complete_rounds'], 2)
        self.assertEqual(result['unconfirmed_steps'], [])

        revisions = [round_['revision'] for round_ in result['rounds']]
        self.assertEqual(revisions, [1, 2])
        keys = [round_['business_key'] for round_ in result['rounds']]
        self.assertEqual(keys, [f'{self.plan_id}:月卡:v1', f'{self.plan_id}:季度卡:v2'])

        for round_ in result['rounds']:
            self.assertTrue(round_['complete'])
            self.assertEqual(round_['offer_state'], 'active')
            self.assertEqual([s['stage'] for s in round_['stages']],
                             ['selection', 'rights', 'checkout'])
            self.assertTrue(all(s['state'] == 'observed' for s in round_['stages']))

        # 结算价格必须与该轮规格自身价格一致，且各自带当前规格前缀，证明没有跨轮拼接
        checkout = {r['tier']: next(s for s in r['stages'] if s['stage'] == 'checkout')
                    for r in result['rounds']}
        self.assertIn('月卡：', checkout['月卡']['checkout_revision_text'])
        self.assertIn('季度卡：', checkout['季度卡']['checkout_revision_text'])
        self.assertEqual(checkout['月卡']['price'], 99)
        self.assertEqual(checkout['季度卡']['price'], 279)

    def test_simulated_expiry_is_observed_not_quoted(self):
        result = observe_plan(self.origin, self.plan_id, ['月卡'], simulate_expiry=True)
        self.assertEqual(len(result['rounds']), 2)
        expired_round = result['rounds'][-1]
        self.assertEqual(expired_round['offer_state'], 'expired')
        self.assertFalse(expired_round['complete'])
        checkout = next(s for s in expired_round['stages'] if s['stage'] == 'checkout')
        self.assertEqual(checkout['state'], 'offer_expired')
        self.assertIn('活动已失效', checkout['evidence']['text'])
        # 未确认/失效步骤必须显式列出，运营一眼能看到哪一步没确认
        self.assertTrue(any('checkout(offer_expired)' in step for step in result['unconfirmed_steps']))

    def test_origin_restriction_is_enforced_for_observation(self):
        with self.assertRaises(ValueError):
            observe_plan('https://example.com/', self.plan_id)

    def test_unknown_tier_is_rejected(self):
        with self.assertRaises(ValueError):
            observe_plan(self.origin, self.plan_id, ['年卡'])

    def test_no_order_is_submitted_and_network_is_loopback_only(self):
        result = observe_plan(self.origin, self.plan_id, ['月卡'])
        safety = result['safety']
        self.assertFalse(safety['order_submitted'])
        self.assertEqual(safety['submit_controls_found'], 0)
        self.assertEqual(safety['network_guard'], 'loopback_read_only')
        self.assertNotIn('submit', [click.lower() for click in safety['clicks']])

    def test_evidence_files_are_written_per_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / 'evidence'
            observe_plan(self.origin, self.plan_id, ['月卡'], evidence_dir=evidence)
            files = sorted(p.name for p in evidence.iterdir())
            self.assertTrue(any(name.endswith('_selection.png') for name in files))
            self.assertTrue(any(name.endswith('_rights.png') for name in files))
            self.assertTrue(any(name.endswith('_checkout.png') for name in files))
            self.assertTrue(any(name.endswith('.html') for name in files))
            for png in evidence.glob('*.png'):
                self.assertGreater(png.stat().st_size, 0)

    def test_observation_receipts_are_append_only(self):
        first = observe_plan(self.origin, self.plan_id, ['月卡'])
        second = observe_plan(self.origin, self.plan_id, ['季度卡'])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'observations.sqlite3'
            self.assertEqual(save_observations(database, [first]), 1)
            self.assertEqual(save_observations(database, [second]), 1)
            with sqlite3.connect(database) as db:
                rows = db.execute(
                    'SELECT tier, offer_revision, complete, business_key FROM plan_observations '
                    'ORDER BY observation_id'
                ).fetchall()
            # 两次独立浏览器会话各自从 v1 开始；季度卡会话发生一次规格切换，版本递增到 v2
            self.assertEqual(rows, [
                ('月卡', 1, 1, f'{self.plan_id}:月卡:v1'),
                ('季度卡', 2, 1, f'{self.plan_id}:季度卡:v2'),
            ])
            receipts = read_observations(database)
            self.assertEqual([row['round']['tier'] for row in receipts], ['月卡', '季度卡'])

    def test_review_view_carries_stage_states_and_unconfirmed_steps(self):
        result = observe_plan(self.origin, self.plan_id, ['月卡'], simulate_expiry=True)
        review = review_observations([result])
        self.assertEqual(len(review), 2)
        active, expired = review
        self.assertTrue(active['complete_quote'])
        self.assertEqual([s['state_label'] for s in active['stages']],
                         ['已确认', '已确认', '已确认'])
        self.assertFalse(expired['complete_quote'])
        self.assertTrue(any('checkout' in step for step in expired['unconfirmed_steps']))
        self.assertFalse(any(row['order_submitted'] for row in review))

    def test_price_drift_is_recorded_without_merging_quotes(self):
        # 用独立页面人为改写结算区，模拟“介绍页与结算弹层不同步”的现场
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.origin + 'detail?id=' + self.plan_id, wait_until='domcontentloaded')
                page.locator('#tier').select_option('季度卡')
                # 令结算终态保留旧规格价格，且不带当前规格前缀
                page.evaluate(
                    "() => { document.querySelector('#checkout-revision').textContent='月卡：99 元'; }")
                from app.domain import classify_checkout, parse_tier_price
                verdict = classify_checkout(
                    '季度卡', '2', page.locator('#checkout-revision').inner_text(),
                    False, parse_tier_price(page.locator('#summary').inner_text()))
                self.assertEqual(verdict['state'], 'unconfirmed')
                self.assertEqual(verdict['reason'], 'checkout_tier_mismatch')
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
