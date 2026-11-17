"""使用真实 Chromium 浏览公开目录，并在授权的本地详情页走完整业务流程。

采集边界：
- 只允许环回来源（127.0.0.1 / localhost）的 GET/HEAD 请求，其余一律拦截；
- 只与规格选择、权益、结算预览、失效模拟四个页面控件交互，不点击任何提交控件；
- 每个规格独立成轮，轮次以页面自身的 offer 版本号为锚点，绝不把前后两轮
  的权益与结算拼成同一份报价；
- 弹层异步渲染时等待终态，超时则如实记为未确认，重试只做只读等待，不重复下单。
"""
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .domain import (
    KNOWN_TIERS, STAGE_SELECTION, STAGE_RIGHTS, STAGE_CHECKOUT,
    OBSERVED, OFFER_EXPIRED, UNCONFIRMED, PENDING_MARKERS,
    interpret_card, interpret_entry, parse_tier_price, classify_rights,
    classify_checkout, round_business_key, round_is_complete,
)

ALLOWED_HOSTS = ('127.0.0.1', 'localhost')
SAFE_METHODS = ('GET', 'HEAD')
DEFAULT_TIMEOUT_MS = 4000
POLL_INTERVAL_MS = 50


def _assert_local_origin(origin):
    parts = urlsplit(origin)
    if parts.hostname not in ALLOWED_HOSTS or parts.scheme != 'http':
        raise ValueError('只允许本地演练来源')
    return parts


def read_catalog(origin):
    _assert_local_origin(origin)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(origin, wait_until='domcontentloaded')
            if not page.locator('main').count():
                raise ValueError('来源目录未加载')
            items = page.locator('.card').evaluate_all('(nodes) => nodes.map(n => ({id:n.dataset.key,name:n.querySelector("h2").textContent,summary:n.querySelector("p").textContent,href:n.querySelector("a").getAttribute("href")}))')
            return [{'source':page.url, **item, 'catalog_fact':interpret_card(item)} for item in items]
        finally:
            browser.close()

def read_plan_page(origin, plan_id, selection=None):
    _assert_local_origin(origin)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(origin, wait_until='domcontentloaded')
            card = page.locator(f'.card[data-key="{plan_id}"]')
            if card.count() != 1:
                raise ValueError('card identity is not unique')
            catalog = {'id': plan_id, 'summary': card.locator('p').inner_text()}
            card.locator('a').click()
            if page.locator('main').get_attribute('data-key') != plan_id:
                raise ValueError('detail identity differs from catalog')
            if selection is not None:
                page.locator('#tier').select_option(selection)
            catalog_fact = interpret_card(catalog)
            entry_signal = {'tier': page.locator('#tier').input_value(),
                            'revision': page.locator('#offer-revision').get_attribute('data-revision')}
            return {'id': plan_id, 'source': page.url, 'catalog_fact': catalog_fact,
                    'opening_summary': page.locator('#summary').inner_text(),
                    'detail_fact': interpret_entry(catalog_fact, entry_signal)}
        finally:
            browser.close()


# --------------------------------------------------------------------------- #
# 完整业务流程：选择规格 -> 打开权益 -> 结算预览，逐轮留证
# --------------------------------------------------------------------------- #

def _install_network_guard(page):
    """只放行环回来源的只读请求；任何外发或写操作在浏览器内即被拦截。"""
    def guard(route):
        request = route.request
        target = urlsplit(request.url)
        if target.scheme == 'http' and target.hostname in ALLOWED_HOSTS and request.method in SAFE_METHODS:
            return route.continue_()
        return route.abort('blockedbyclient')
    page.route('**/*', guard)


def _is_pending(text):
    return any(marker in (text or '') for marker in PENDING_MARKERS)


def _wait_until_settled(page, locator, timeout_ms):
    """等待输出区离开空/读取中状态。超时不抛异常，返回当前文本交给分类器。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        text = locator.inner_text()
        if text and not _is_pending(text):
            return text
        if time.monotonic() >= deadline:
            return text
        page.wait_for_timeout(POLL_INTERVAL_MS)


def _offer_state(page):
    offer = page.locator('#offer-revision')
    revision = offer.get_attribute('data-revision')
    expired = offer.get_attribute('data-expired') == 'true'
    return revision, expired, offer.inner_text()


def _save_evidence(page, evidence_dir, plan_id, round_no, stage):
    if evidence_dir is None:
        return None
    target = Path(evidence_dir)
    target.mkdir(parents=True, exist_ok=True)
    shot = target / f'{plan_id}_round{round_no}_{stage}.png'
    page.screenshot(path=str(shot), full_page=True)
    return str(shot)


def _stage_record(stage, state, reason, **extra):
    record = {'stage': stage, 'state': state, 'reason': reason}
    record.update(extra)
    return record


def _observe_one_round(page, plan_id, round_no, tier, catalog_fact, evidence_dir, timeout_ms):
    """完整走一轮：选择规格 -> 权益 -> 结算预览。任何一步失败只标记该步，不拼接。"""
    stages = []

    # 1) 选择规格：切换会清空权益与结算，并让 offer 版本号递增。
    #    已是目标规格时不重复 select_option——浏览器对同值选择仍可能派发 change，
    #    会制造一个没有任何选择动作的“空转”新版本，污染轮次锚点。
    if page.locator('#tier').input_value() != tier:
        page.locator('#tier').select_option(tier)
    page.wait_for_function(
        '(sel) => document.querySelector("#tier").value === sel', arg=tier, timeout=timeout_ms)
    revision, offer_expired, offer_text = _offer_state(page)
    summary_text = page.locator('#summary').inner_text()
    tier_price = parse_tier_price(summary_text)

    # 选择阶段确认：下拉值已是目标规格、offer 版本可读、规格价格可读。
    # 注意默认规格下 #summary 可能保留目录条件文案（如“月付”），规格与价格的
    # 强绑定在权益/结算阶段通过弹层文本的规格前缀再次校验。
    current_value = page.locator('#tier').input_value()
    selection_ok = (
        current_value == tier
        and tier in KNOWN_TIERS
        and isinstance(revision, str) and revision.isdigit()
        and tier_price is not None
    )
    selection_state = OBSERVED if selection_ok else UNCONFIRMED
    selection_reason = 'confirmed' if selection_ok else 'selection_state_unread'
    stages.append(_stage_record(
        STAGE_SELECTION, selection_state, selection_reason,
        tier=tier, revision=int(revision) if revision and revision.isdigit() else revision,
        offer_state='expired' if offer_expired else 'active',
        offer_text=offer_text, price_text=tier_price['price_text'] if tier_price else None,
        evidence={'summary_text': summary_text}))
    selection_shot = _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_SELECTION)

    # 2) 打开权益弹层（异步渲染，等待终态）
    rights_extra = {}
    try:
        page.locator('#rights').click()
        rights_text = _wait_until_settled(page, page.locator('#rights-revision'), timeout_ms)
        legacy_text = page.locator('#rights-text').inner_text()
        verdict = classify_rights(tier, revision, rights_text, offer_expired)
        rights_extra = {
            'tier': tier, 'revision': int(revision) if revision and revision.isdigit() else revision,
            'rights_revision_text': rights_text, 'rights_panel_text': legacy_text,
            'evidence': {'locator': '#rights-revision', 'text': rights_text,
                         'secondary_locator': '#rights-text', 'secondary_text': legacy_text,
                         'screenshot': _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_RIGHTS)},
        }
        rights_extra.update({k: v for k, v in verdict.items() if k in ('rights_text', 'evidence_text')})
        stages.append(_stage_record(STAGE_RIGHTS, verdict['state'], verdict['reason'], **rights_extra))
    except PlaywrightTimeoutError:
        stages.append(_stage_record(STAGE_RIGHTS, UNCONFIRMED, 'rights_wait_timeout', tier=tier,
                                    evidence={'screenshot': _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_RIGHTS)}))
    except Exception as exc:  # 浏览器异常只影响本阶段，留痕后继续
        stages.append(_stage_record(STAGE_RIGHTS, UNCONFIRMED, f'browser_error:{type(exc).__name__}', tier=tier))

    # 版本锚点校验：打开权益不应改变 offer 版本；变了说明状态被外部改写，本轮作废处理
    mid_revision, _, _ = _offer_state(page)
    if mid_revision != revision:
        stages[-1] = _stage_record(STAGE_RIGHTS, UNCONFIRMED, 'revision_changed_mid_round',
                                   tier=tier, expected_revision=revision, observed_revision=mid_revision)
        revision = mid_revision

    # 3) 结算预览（异步渲染，可能提示活动失效）
    try:
        page.locator('#preview').click()
        checkout_text = _wait_until_settled(page, page.locator('#checkout-revision'), timeout_ms)
        result_text = page.locator('#result').inner_text()
        verdict = classify_checkout(tier, revision, checkout_text, offer_expired, tier_price, result_text)
        checkout_extra = {
            'tier': tier, 'revision': int(revision) if revision and revision.isdigit() else revision,
            'checkout_revision_text': checkout_text, 'result_panel_text': result_text,
            'evidence': {'locator': '#checkout-revision', 'text': checkout_text,
                         'secondary_locator': '#result', 'secondary_text': result_text,
                         'screenshot': _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_CHECKOUT)},
        }
        for key in ('price', 'price_text', 'tier_price_text', 'evidence_text'):
            if key in verdict:
                checkout_extra[key] = verdict[key]
        stages.append(_stage_record(STAGE_CHECKOUT, verdict['state'], verdict['reason'], **checkout_extra))
    except PlaywrightTimeoutError:
        stages.append(_stage_record(STAGE_CHECKOUT, UNCONFIRMED, 'checkout_wait_timeout', tier=tier,
                                    evidence={'screenshot': _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_CHECKOUT)}))
    except Exception as exc:
        stages.append(_stage_record(STAGE_CHECKOUT, UNCONFIRMED, f'browser_error:{type(exc).__name__}', tier=tier))

    end_revision, end_expired, _ = _offer_state(page)
    html_snapshot = None
    if evidence_dir is not None:
        target = Path(evidence_dir)
        target.mkdir(parents=True, exist_ok=True)
        html_path = target / f'{plan_id}_round{round_no}.html'
        html_path.write_text(page.content(), encoding='utf-8')
        html_snapshot = str(html_path)

    round_record = {
        'round': round_no,
        'tier': tier,
        'revision': int(revision) if revision and revision.isdigit() else revision,
        'business_key': round_business_key(plan_id, tier, revision) if revision and str(revision).isdigit() else None,
        'offer_state': 'expired' if end_expired else 'active',
        'stages': stages,
        'evidence': {'selection_screenshot': selection_shot, 'html_snapshot': html_snapshot},
    }
    round_record['complete'] = round_is_complete(round_record)
    return round_record


def observe_plan(origin, plan_id, tiers=None, *, evidence_dir=None,
                 simulate_expiry=False, timeout_ms=DEFAULT_TIMEOUT_MS):
    """在授权的本地详情页对每个规格走完整浏览器流程并逐轮留证。

    返回结构中的每个 round 都是一次独立观察：带规格、offer 版本、三个阶段
    的有效性、未确认原因与页面证据（截图/HTML/定位器原文）。
    本函数不会点击任何提交控件，也不会产生真实订单。
    """
    _assert_local_origin(origin)
    tiers = list(tiers) if tiers else list(KNOWN_TIERS)
    unknown = [tier for tier in tiers if tier not in KNOWN_TIERS]
    if unknown:
        raise ValueError(f'未知规格：{unknown}')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            _install_network_guard(page)
            page.goto(origin, wait_until='domcontentloaded')

            card = page.locator(f'.card[data-key="{plan_id}"]')
            if card.count() != 1:
                raise ValueError('card identity is not unique')
            catalog = {'id': plan_id, 'summary': card.locator('p').inner_text()}
            catalog_fact = interpret_card(catalog)
            card.locator('a').click()
            if page.locator('main').get_attribute('data-key') != plan_id:
                raise ValueError('detail identity differs from catalog')

            # 安全检查：页面若存在任何提交控件，拒绝继续，避免误触真实下单
            submit_count = page.locator(
                'form, button[type="submit"], input[type="submit"]').count()
            if submit_count:
                raise ValueError('页面存在提交控件，采集流程拒绝在该页面运行')

            rounds = []
            for round_no, tier in enumerate(tiers, start=1):
                rounds.append(_observe_one_round(
                    page, plan_id, round_no, tier, catalog_fact, evidence_dir, timeout_ms))

            if simulate_expiry:
                # 由页面自带控件模拟活动失效，再观察一轮结算失效的呈现
                page.locator('#expire').click()
                page.wait_for_function(
                    '() => document.querySelector("#offer-revision").dataset.expired === "true"',
                    timeout=timeout_ms)
                current_tier = page.locator('#tier').input_value()
                rounds.append(_observe_expired_round(
                    page, plan_id, len(rounds) + 1, current_tier, evidence_dir, timeout_ms))

            unconfirmed_steps = [
                f"第{record['round']}轮/{record['tier']}/{stage['stage']}({stage['reason']})"
                for record in rounds for stage in record['stages']
                if stage['state'] != OBSERVED
            ]
            return {
                'id': plan_id,
                'source': page.url,
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'catalog_fact': catalog_fact,
                'safety': {
                    'network_guard': 'loopback_read_only',
                    'submit_controls_found': submit_count,
                    'order_submitted': False,
                    'clicks': ['#tier', '#rights', '#preview'] + (['#expire'] if simulate_expiry else []),
                },
                'rounds': rounds,
                'complete_rounds': sum(1 for record in rounds if record['complete']),
                'unconfirmed_steps': unconfirmed_steps,
            }
        finally:
            browser.close()


def _observe_expired_round(page, plan_id, round_no, tier, evidence_dir, timeout_ms):
    """失效轮：不再切换规格（切换会被误读为新一轮状态），只读权益与结算。"""
    revision, offer_expired, offer_text = _offer_state(page)
    stages = [_stage_record(
        STAGE_SELECTION, OFFER_EXPIRED, 'offer_expired',
        tier=tier, revision=int(revision) if revision and revision.isdigit() else revision,
        offer_state='expired', offer_text=offer_text,
        evidence={'summary_text': page.locator('#summary').inner_text()})]
    selection_shot = _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_SELECTION)

    page.locator('#rights').click()
    rights_text = _wait_until_settled(page, page.locator('#rights-revision'), timeout_ms)
    rights_verdict = classify_rights(tier, revision, rights_text, offer_expired=True)
    stages.append(_stage_record(
        STAGE_RIGHTS, rights_verdict['state'], rights_verdict['reason'], tier=tier,
        rights_revision_text=rights_text,
        rights_panel_text=page.locator('#rights-text').inner_text(),
        evidence={'locator': '#rights-revision', 'text': rights_text,
                  'screenshot': _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_RIGHTS)}))

    page.locator('#preview').click()
    checkout_text = _wait_until_settled(page, page.locator('#checkout-revision'), timeout_ms)
    result_text = page.locator('#result').inner_text()
    checkout_verdict = classify_checkout(
        tier, revision, checkout_text, True,
        parse_tier_price(page.locator('#summary').inner_text()), result_text)
    stages.append(_stage_record(
        STAGE_CHECKOUT, checkout_verdict['state'], checkout_verdict['reason'], tier=tier,
        checkout_revision_text=checkout_text, result_panel_text=result_text,
        evidence={'locator': '#checkout-revision', 'text': checkout_text,
                  'secondary_locator': '#result', 'secondary_text': result_text,
                  'screenshot': _save_evidence(page, evidence_dir, plan_id, round_no, STAGE_CHECKOUT)}))

    record = {
        'round': round_no, 'tier': tier,
        'revision': int(revision) if revision and revision.isdigit() else revision,
        'business_key': round_business_key(plan_id, tier, revision) if revision and str(revision).isdigit() else None,
        'offer_state': 'expired', 'stages': stages,
        'evidence': {'selection_screenshot': selection_shot, 'html_snapshot': None},
    }
    record['complete'] = round_is_complete(record)
    return record
