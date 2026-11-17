import unittest

from app.domain import (
    parse_tier_price, classify_rights, classify_checkout,
    round_business_key, round_is_complete,
    OBSERVED, OFFER_EXPIRED, UNCONFIRMED,
)


class TierPriceTest(unittest.TestCase):
    def test_parse_summary_price(self):
        parsed = parse_tier_price('季度卡 · 279 元')
        self.assertEqual(parsed, {'tier': '季度卡', 'price': 279, 'price_text': '279 元'})

    def test_malformed_summary_is_unread(self):
        self.assertIsNone(parse_tier_price('活动异常'))
        self.assertIsNone(parse_tier_price(''))


class RightsClassificationTest(unittest.TestCase):
    def test_confirmed_rights_must_carry_current_tier(self):
        verdict = classify_rights('月卡', '1', '月卡：权益版本 1', False)
        self.assertEqual(verdict['state'], OBSERVED)
        self.assertEqual(verdict['rights_text'], '权益版本 1')

    def test_pending_and_empty_are_unconfirmed(self):
        self.assertEqual(classify_rights('月卡', '1', '权益读取中', False)['state'], UNCONFIRMED)
        self.assertEqual(classify_rights('月卡', '1', '', False)['state'], UNCONFIRMED)

    def test_stale_tier_prefix_is_not_stitched_into_current_round(self):
        # 当前规格是季度卡，弹层却还是月卡文本：不得当作季度卡的权益
        verdict = classify_rights('季度卡', '2', '月卡：权益版本 1', False)
        self.assertEqual(verdict['state'], UNCONFIRMED)
        self.assertEqual(verdict['reason'], 'rights_tier_mismatch')

    def test_expired_offer_keeps_rights_evidence_but_marks_expired(self):
        verdict = classify_rights('季度卡', '3', '季度卡：权益版本 3', True)
        self.assertEqual(verdict['state'], OFFER_EXPIRED)
        self.assertIn('权益版本 3', verdict['evidence_text'])


class CheckoutClassificationTest(unittest.TestCase):
    def test_confirmed_checkout_extracts_price(self):
        verdict = classify_checkout(
            '月卡', '1', '月卡：结算版本 1', False, {'tier': '月卡', 'price': 99, 'price_text': '99 元'})
        self.assertEqual(verdict['state'], OBSERVED)
        self.assertEqual(verdict['price'], 99)

    def test_expired_checkout(self):
        verdict = classify_checkout('季度卡', '3', '季度卡：活动已失效', True, None)
        self.assertEqual(verdict['state'], OFFER_EXPIRED)

    def test_pending_checkout_is_unconfirmed(self):
        verdict = classify_checkout('月卡', '1', '结算读取中', False, None)
        self.assertEqual(verdict['state'], UNCONFIRMED)
        self.assertEqual(verdict['reason'], 'checkout_panel_pending')

    def test_price_drift_between_tier_and_checkout_is_flagged_not_merged(self):
        # 规格自身价 279，结算预览却报 99：标记漂移，保留两份证据，不合成一个报价
        verdict = classify_checkout(
            '季度卡', '2', '季度卡：99 元', False,
            {'tier': '季度卡', 'price': 279, 'price_text': '279 元'})
        self.assertEqual(verdict['state'], UNCONFIRMED)
        self.assertEqual(verdict['reason'], 'checkout_price_drift')
        self.assertEqual(verdict['tier_price_text'], '279 元')
        self.assertEqual(verdict['price_text'], '99 元')

    def test_wrong_tier_prefix_is_unconfirmed(self):
        verdict = classify_checkout('季度卡', '2', '月卡：结算版本 1', False, None)
        self.assertEqual(verdict['state'], UNCONFIRMED)
        self.assertEqual(verdict['reason'], 'checkout_tier_mismatch')

    def test_version_stamp_without_price_falls_back_to_tier_price(self):
        verdict = classify_checkout(
            '月卡', '1', '月卡：结算版本 1', False,
            {'tier': '月卡', 'price': 99, 'price_text': '99 元'})
        self.assertEqual(verdict['state'], OBSERVED)
        self.assertEqual(verdict['price'], 99)
        self.assertEqual(verdict['price_source'], 'tier_summary')

    def test_result_panel_price_is_used_when_version_stamp_has_none(self):
        verdict = classify_checkout(
            '月卡', '1', '月卡：结算版本 1', False,
            {'tier': '月卡', 'price': 99, 'price_text': '99 元'},
            result_text='月卡：99 元')
        self.assertEqual(verdict['state'], OBSERVED)
        self.assertEqual(verdict['price'], 99)
        self.assertNotIn('price_source', verdict)

    def test_expired_offer_overrides_stale_active_text(self):
        # 结算区文本还没来得及失效，但 offer 已标记失效：以 offer 状态为准
        verdict = classify_checkout(
            '季度卡', '3', '季度卡：结算版本 3', True,
            {'tier': '季度卡', 'price': 279, 'price_text': '279 元'})
        self.assertEqual(verdict['state'], OFFER_EXPIRED)


class RoundAssemblyTest(unittest.TestCase):
    def _round(self, states):
        return {'stages': [
            {'stage': stage, 'state': state} for stage, state in states]}

    def test_business_key_carries_tier_and_revision(self):
        self.assertEqual(round_business_key('ai-basic', '季度卡', '2'), 'ai-basic:季度卡:v2')

    def test_complete_requires_all_three_stages_observed(self):
        complete = self._round([
            ('selection', OBSERVED), ('rights', OBSERVED), ('checkout', OBSERVED)])
        self.assertTrue(round_is_complete(complete))

    def test_expired_or_missing_stage_breaks_completeness(self):
        expired = self._round([
            ('selection', OFFER_EXPIRED), ('rights', OFFER_EXPIRED), ('checkout', OFFER_EXPIRED)])
        self.assertFalse(round_is_complete(expired))
        partial = self._round([('selection', OBSERVED), ('rights', UNCONFIRMED)])
        self.assertFalse(round_is_complete(partial))


if __name__ == '__main__':
    unittest.main()
