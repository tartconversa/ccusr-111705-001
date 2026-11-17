"""只审阅已观察的详情入口与完整轮次，不把候选记录当作已完成的业务。"""

STATE_LABELS = {
    'observed': '已确认',
    'offer_expired': '活动失效',
    'unconfirmed': '未确认',
}

STAGE_LABELS = {
    'selection': '选择规格',
    'rights': '打开权益',
    'checkout': '结算预览',
}

def review_entries(entries):
    observations = []
    for entry in entries:
        fact = entry['detail_fact']
        observations.append({'offer': fact['business_key'], 'catalog_price': entry['catalog_fact']['price'],
                             'stage': 'selection_seen', 'rights': 'not_observed', 'checkout': 'not_observed'})
    return observations


def review_observations(observations):
    """把完整观察流程压成运营核对视图：每行一个规格轮次，逐阶段标状态。"""
    review = []
    for observation in observations:
        catalog_price = observation['catalog_fact']['price']
        for record in observation['rounds']:
            stages = {stage['stage']: stage for stage in record['stages']}
            row = {
                'item_id': observation['id'],
                'round': record['round'],
                'tier': record['tier'],
                'business_key': record.get('business_key'),
                'offer_revision': record.get('revision'),
                'offer_state': record.get('offer_state'),
                'catalog_price': catalog_price,
                'complete_quote': record['complete'],
                'stages': [],
                'unconfirmed_steps': [],
                'order_submitted': observation['safety']['order_submitted'],
            }
            for key in ('selection', 'rights', 'checkout'):
                stage = stages.get(key)
                if stage is None:
                    row['stages'].append({'stage': key, 'label': STAGE_LABELS[key],
                                          'state': 'unconfirmed', 'state_label': STATE_LABELS['unconfirmed'],
                                          'reason': 'stage_not_reached'})
                    row['unconfirmed_steps'].append(f'{key}(stage_not_reached)')
                    continue
                entry = {'stage': key, 'label': STAGE_LABELS[key],
                         'state': stage['state'], 'state_label': STATE_LABELS.get(stage['state'], stage['state']),
                         'reason': stage['reason']}
                if 'price_text' in stage:
                    entry['price_text'] = stage['price_text']
                row['stages'].append(entry)
                if stage['state'] != 'observed':
                    row['unconfirmed_steps'].append(f"{key}({stage['reason']})")
            checkout = stages.get('checkout')
            if checkout and checkout.get('reason') == 'checkout_price_drift':
                row['price_drift'] = {
                    'tier_price_text': checkout.get('tier_price_text'),
                    'checkout_price_text': checkout.get('price_text'),
                }
            review.append(row)
    return review
