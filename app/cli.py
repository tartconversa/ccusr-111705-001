"""本地演练采集演示：目录读取与完整权益/结算观察。"""
import argparse
import json

from .capture import read_catalog, observe_plan
from .records import save_catalog, save_observations
from .review import review_observations

DEFAULT_ORIGIN = 'http://127.0.0.1:8765/'


def main(argv=None):
    parser = argparse.ArgumentParser(description='本地会员卡资料采集（仅环回来源）')
    sub = parser.add_subparsers(dest='command')

    catalog_cmd = sub.add_parser('catalog', help='读取公开目录（默认命令）')
    catalog_cmd.add_argument('--origin', default=DEFAULT_ORIGIN)
    catalog_cmd.add_argument('--db', help='可选：把目录收据写入 SQLite')

    observe_cmd = sub.add_parser('observe', help='走完整规格/权益/结算流程并留证')
    observe_cmd.add_argument('plan_id', help='目录卡片 data-key，例如 ai-basic')
    observe_cmd.add_argument('--origin', default=DEFAULT_ORIGIN)
    observe_cmd.add_argument('--tier', action='append', choices=('月卡', '季度卡'),
                             help='指定规格，可重复；默认全部规格')
    observe_cmd.add_argument('--evidence-dir', help='截图与 HTML 快照目录')
    observe_cmd.add_argument('--simulate-expiry', action='store_true',
                             help='用页面控件模拟活动失效并追加一轮观察')
    observe_cmd.add_argument('--db', help='可选：把观察收据追加写入 SQLite')

    args = parser.parse_args(argv)
    if args.command in (None, 'catalog'):
        origin = getattr(args, 'origin', DEFAULT_ORIGIN)
        items = read_catalog(origin)
        if getattr(args, 'db', None):
            save_catalog(args.db, items)
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return

    observation = observe_plan(
        args.origin, args.plan_id, args.tier,
        evidence_dir=args.evidence_dir,
        simulate_expiry=args.simulate_expiry)
    if args.db:
        save_observations(args.db, [observation])
    print(json.dumps(
        {'observation': observation, 'review': review_observations([observation])},
        ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
