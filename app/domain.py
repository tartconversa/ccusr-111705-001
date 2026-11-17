"""直播间 AI 会员权益的可证明采集：目录卡片与分阶段观察的数据约定。"""
import re

# 页面允许选择的规格（与详情页 #tier 选项一致）
KNOWN_TIERS = ('月卡', '季度卡')

# 观察阶段：选择规格 / 打开权益 / 结算预览
STAGE_SELECTION = 'selection'
STAGE_RIGHTS = 'rights'
STAGE_CHECKOUT = 'checkout'
STAGES = (STAGE_SELECTION, STAGE_RIGHTS, STAGE_CHECKOUT)

# 观察有效性：确认成功 / 活动失效 / 未能确认
OBSERVED = 'observed'
OFFER_EXPIRED = 'offer_expired'
UNCONFIRMED = 'unconfirmed'
OBSERVATION_STATES = (OBSERVED, OFFER_EXPIRED, UNCONFIRMED)

# 弹层异步渲染时的占位文本
PENDING_MARKERS = ('读取中', '核对中')

_PRICE_RE = re.compile(r'(?P<amount>\d+)\s*元')


def interpret_card(item):
    parts = item['summary'].split(' · ', 1)
    if len(parts) != 2:
        raise ValueError('卡片摘要格式无效')
    condition, observation = parts
    found = re.fullmatch(r"(?P<amount>\d+) 元", observation)
    if not found:
        raise ValueError('卡片状态未识别')
    amount = found.group('amount')
    return {'kind': 'plan', 'identity': item['id'], 'condition': condition, 'price_text': observation, 'price': int(amount) if amount.isdigit() else amount}

def interpret_entry(catalog_fact, signal):
    if signal['tier'] not in ('月卡', '季度卡') or not signal['revision'].isdigit():
        raise ValueError('invalid offer selection or revision')
    return {'business_key': f"{catalog_fact['identity']}:{signal['tier']}:v{signal['revision']}",
            'tier': signal['tier'], 'offer_revision': int(signal['revision'])}


def parse_tier_price(summary_text):
    """从 #summary 文本解析当前规格价格，例如 '季度卡 · 279 元' -> ('季度卡', 279, '279 元')。"""
    parts = (summary_text or '').split(' · ', 1)
    if len(parts) != 2:
        return None
    tier, price_text = parts[0].strip(), parts[1].strip()
    match = _PRICE_RE.fullmatch(price_text)
    if not match:
        return None
    return {'tier': tier, 'price': int(match.group('amount')), 'price_text': price_text}


def _split_tier_prefix(text):
    """'月卡：权益版本 1' -> ('月卡', '权益版本 1')；无法切分时返回 (None, text)。"""
    if not text:
        return None, ''
    for separator in ('：', ':'):
        if separator in text:
            prefix, remainder = text.split(separator, 1)
            return prefix.strip(), remainder.strip()
    return None, text.strip()


def _is_pending(text):
    return any(marker in (text or '') for marker in PENDING_MARKERS)


def classify_rights(tier, revision, text, offer_expired):
    """分类权益弹层观察。只接受带当前规格前缀、且属于当前版本轮次的文本。

    失效后页面仍可能渲染权益文本，因此有效性以 offer_expired 为准，
    不把失效轮次里的权益文本当成有效承诺。
    """
    if not text:
        return {'state': UNCONFIRMED, 'reason': 'rights_panel_empty'}
    if _is_pending(text):
        return {'state': UNCONFIRMED, 'reason': 'rights_panel_pending'}
    prefix, body = _split_tier_prefix(text)
    if prefix != tier:
        return {'state': UNCONFIRMED, 'reason': 'rights_tier_mismatch', 'evidence_text': text}
    if offer_expired:
        return {'state': OFFER_EXPIRED, 'reason': 'offer_expired', 'evidence_text': text, 'rights_text': body}
    return {'state': OBSERVED, 'reason': 'confirmed', 'evidence_text': text, 'rights_text': body}


def classify_checkout(tier, revision, text, offer_expired, tier_price, result_text=''):
    """分类结算预览观察，并核对预览价格与当前规格价格是否一致。

    页面有两处结算证据：版本锚点（'月卡：结算版本 1'，不含价格）与结果区
    （'月卡：99 元'，含价格）。任一区域读出价格即可核对；版本戳本身确认
    该预览属于当前轮次，但价格缺失时必须如实标记未确认。
    """
    if not text:
        return {'state': UNCONFIRMED, 'reason': 'checkout_panel_empty'}
    if _is_pending(text):
        return {'state': UNCONFIRMED, 'reason': 'checkout_panel_pending'}
    prefix, body = _split_tier_prefix(text)
    if prefix != tier:
        return {'state': UNCONFIRMED, 'reason': 'checkout_tier_mismatch', 'evidence_text': text}
    if '活动已失效' in body or '活动已失效' in text or offer_expired:
        return {'state': OFFER_EXPIRED, 'reason': 'offer_expired', 'evidence_text': text}
    price_match = _PRICE_RE.search(body)
    if not price_match:
        # 版本戳确认了轮次但不含价格：从结果区证据取价
        result_prefix, result_body = _split_tier_prefix(result_text)
        result_match = _PRICE_RE.search(result_body) if result_prefix == tier else None
        if result_match:
            price_match = result_match
            text = result_text
            body = result_body
        elif '结算版本' in body and tier_price is not None:
            # 只有版本戳：以该规格自身价作为预览价的唯一可读来源
            return {'state': OBSERVED, 'reason': 'confirmed_without_inline_price',
                    'evidence_text': text, 'price': tier_price['price'],
                    'price_text': tier_price['price_text'], 'price_source': 'tier_summary'}
        else:
            return {'state': UNCONFIRMED, 'reason': 'checkout_price_unread', 'evidence_text': text}
    price = int(price_match.group('amount'))
    result = {'state': OBSERVED, 'reason': 'confirmed', 'evidence_text': text,
              'price': price, 'price_text': price_match.group(0)}
    if tier_price is not None and price != tier_price.get('price'):
        # 预览价格与规格自身价格不一致：保留证据，标记为漂移，不合并成一个报价
        result['state'] = UNCONFIRMED
        result['reason'] = 'checkout_price_drift'
        result['tier_price_text'] = tier_price.get('price_text')
    return result


def round_business_key(identity, tier, revision):
    return f'{identity}:{tier}:v{revision}'


def round_is_complete(round_record):
    """一轮观察只有三个阶段都确认（非失效、非未确认）才算完整报价。"""
    stages = {stage['stage']: stage for stage in round_record['stages']}
    if set(stages) != set(STAGES):
        return False
    return all(stages[stage]['state'] == OBSERVED for stage in STAGES)
