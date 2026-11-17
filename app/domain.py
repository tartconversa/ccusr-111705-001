"""直播间 AI 会员权益的可证明采集：目录卡片既有数据约定。"""
import re

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
