"""公开目录收据与分阶段观察收据。

目录按身份覆盖；详情入口与完整观察均为只追加——每次浏览器流程都是一条
独立证据，绝不回写或合并历史观察。
"""
import json
import sqlite3
from pathlib import Path

def save_catalog(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS catalog (id TEXT PRIMARY KEY, source TEXT NOT NULL, payload TEXT NOT NULL)')
        for item in items:
            db.execute('INSERT OR REPLACE INTO catalog VALUES (?, ?, ?)', (item['id'], item['source'], json.dumps(item, ensure_ascii=False)))
    return len(items)

def save_detail_entries(path, entries):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS detail_entries (visit_id INTEGER PRIMARY KEY, item_id TEXT NOT NULL, business_key TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL)')
        for entry in entries:
            if entry['catalog_fact']['identity'] != entry['id']:
                raise ValueError('catalog and detail identity mismatch')
            db.execute('INSERT INTO detail_entries (item_id, business_key, source, payload) VALUES (?, ?, ?, ?)',
                       (entry['id'], entry['detail_fact']['business_key'], entry['source'], json.dumps(entry, ensure_ascii=False)))
    return len(entries)

def read_detail_entries(path):
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT payload FROM detail_entries ORDER BY visit_id').fetchall()
    return [json.loads(row[0]) for row in rows]


def save_observations(path, observations):
    """只追加保存完整观察流程结果；每个规格轮次单独成行，便于逐轮核对。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    with sqlite3.connect(path) as db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS plan_observations ('
            'observation_id INTEGER PRIMARY KEY, item_id TEXT NOT NULL, round_no INTEGER NOT NULL,'
            'tier TEXT NOT NULL, offer_revision INTEGER, business_key TEXT, offer_state TEXT,'
            'complete INTEGER NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL)')
        for observation in observations:
            if observation['catalog_fact']['identity'] != observation['id']:
                raise ValueError('catalog and observation identity mismatch')
            for record in observation['rounds']:
                db.execute(
                    'INSERT INTO plan_observations '
                    '(item_id, round_no, tier, offer_revision, business_key, offer_state, complete,'
                    ' source, observed_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (observation['id'], record['round'], record['tier'], record.get('revision'),
                     record.get('business_key'), record.get('offer_state'),
                     1 if record['complete'] else 0, observation['source'],
                     observation['observed_at'], json.dumps(record, ensure_ascii=False)))
                saved += 1
    return saved

def read_observations(path):
    with sqlite3.connect(path) as db:
        rows = db.execute(
            'SELECT item_id, observed_at, payload FROM plan_observations ORDER BY observation_id'
        ).fetchall()
    return [{'item_id': row[0], 'observed_at': row[1], 'round': json.loads(row[2])} for row in rows]
