#!/usr/bin/env python3
"""Manual, read-only preparation. No LLM, article writes, Git operations or schedule."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tempfile

from ad_registry import validate_registry, validate_sources, validate_topic

ROOT = Path(__file__).resolve().parents[1]


def checked_output(root, output):
    out = Path(output).resolve()
    repo = Path(root).resolve()
    if out == repo or repo in out.parents:
        raise ValueError('取得データはリポジトリ外の一時フォルダに保存してください')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('出力先は新しい空フォルダにしてください。古い根拠を再利用しません')
    out.mkdir(parents=True, exist_ok=True)
    return out


def evidence_is_fresh(evidence, hours, now):
    try:
        stamp = dt.datetime.fromisoformat(evidence['fetched_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return False
        age = now - stamp
        return dt.timedelta(0) <= age <= dt.timedelta(hours=hours)
    except (KeyError, TypeError, ValueError):
        return False


def write_report(out, report):
    (out / 'preparation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md = [
        '# 記事生成の再開準備レポート', '',
        '**この実行では記事・PRを作成せず、本番と広告コードを変更しません。**',
        f'実行日時: {report["checked_at"]}', f'状態: {report["status"]}',
        f'公式ページ取得を実行: {report["source_fetch_requested"]}',
        '取得成功は価格・掲載条件・法令適合の確認済みという意味ではありません。',
        '', '## 広告台帳',
    ]
    for a in report['advertisers']:
        md.append(f'- {a["id"]}: 提携={a["approval"]} / 掲載条件={a["conditions"]}')
    md.extend(['', '## 取得した公式出典'])
    for source in report['sources']:
        md.extend([f'- {source["id"]}: {source["url"]}',
                   f'  取得日時: {source["fetched_at"]} / 本文SHA-256: {source["text_sha256"]}'])
    if not report['sources']:
        md.append('この実行で取得できた出典はありません。古い根拠へはフォールバックしません。')
    md.extend(['', '## 停止・要確認事項'])
    md.extend('- ' + error for error in report['errors'])
    md.extend('- ' + blocker for blocker in report['remaining_requirements'])
    md.extend(['', '生成・公開・定期実行は停止したままです。'])
    (out / 'preparation.md').write_text('\n'.join(md) + '\n', encoding='utf-8')


def run(root=ROOT, output=None, fetch=False):
    root = Path(root)
    output = output or tempfile.mkdtemp(prefix='kurashi-preparation-')
    out = checked_output(root, output)
    now = dt.datetime.now(dt.timezone.utc)
    report = {
        'checked_at': now.isoformat(), 'status': 'paused_preparation_only',
        'article_generated': False, 'pr_created': False,
        'scheduled_generation_enabled': False, 'llm_api_called': False,
        'public_files_changed': False, 'facts_verified': False,
        'source_fetch_requested': bool(fetch), 'advertisers': [], 'sources': [], 'errors': [],
        'remaining_requirements': [
            '取得本文から料金・単位・適用条件を根拠引用に対応付け、人間が確認する',
            '掲載条件未登録の案件は、公開しない方法で個別条件を確認・登録する',
            '本文生成AIの方式・認証・費用上限について承認を得る',
            '週1件上限、再実行・並列実行制御、既存slug・未承認PRの重複防止を実装する',
            '下書きPR作成と人間による公開承認を別の実装PRでテストする',
        ],
    }
    registry, catalog, topic = {}, {}, {}
    try:
        registry = json.loads((root / 'ops/affiliate_registry.json').read_text(encoding='utf-8'))
        catalog = json.loads((root / 'ops/official_sources.json').read_text(encoding='utf-8'))
        topic = json.loads((root / 'ops/pilot_topic.json').read_text(encoding='utf-8'))
        report['errors'].extend(validate_registry(registry, root))
        if not report['errors']:
            report['errors'].extend(validate_sources(catalog, registry))
        if not report['errors']:
            report['errors'].extend(validate_topic(topic, registry, catalog, root))
        if isinstance(registry, dict):
            for a in registry.get('advertisers', []):
                if isinstance(a, dict):
                    report['advertisers'].append({'id': a.get('id', 'invalid'),
                        'approval': a.get('approval', {}).get('status', 'unknown'),
                        'conditions': a.get('conditions', {}).get('status', 'unknown')})
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        report['errors'].append('台帳・出典・テーマの読み込みまたは検証に失敗しました: ' + str(exc)[:200])
    if report['errors']:
        report['status'] = 'blocked_invalid_registry_or_topic'
        write_report(out, report)
        return report, 2, out
    if fetch:
        from source_fetch import SourceError, fetch_source
        by_id = {s['id']: s for s in catalog['sources']}
        for sid in topic['source_ids']:
            source = by_id[sid]
            try:
                evidence = fetch_source(source)
                if (evidence.get('fact_verification') != 'not_performed'
                        or evidence.get('trusted_for_instructions') is not False):
                    raise SourceError('取得データの信頼区分が不正です')
                if not evidence_is_fresh(evidence, source['max_age_hours'], dt.datetime.now(dt.timezone.utc)):
                    raise SourceError('出典の取得日時が不正、または鮮度上限を超えています')
                (out / ('evidence-' + sid + '.json')).write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                report['sources'].append({'id': sid, 'url': source['url'],
                    'fetched_at': evidence['fetched_at'], 'text_sha256': evidence['text_sha256']})
            except (SourceError, OSError, ValueError, KeyError) as exc:
                report['errors'].append(sid + ': 公式情報の取得を停止しました: ' + str(exc)[:200])
                break
        report['status'] = ('blocked_source_fetch' if report['errors']
                            else 'sources_acquired_pending_claim_and_model_review')
    write_report(out, report)
    return report, 3 if report['errors'] else 0, out


def main():
    parser = argparse.ArgumentParser(description='準備検査だけ。記事・広告・PR・公開設定を変更しません。')
    parser.add_argument('--output', help='リポジトリ外の新しい空フォルダ。省略時は一時フォルダ。')
    parser.add_argument('--fetch', action='store_true', help='許可された公式URLを取得する。広告URLへは通信しない。')
    args = parser.parse_args()
    try:
        report, code, out = run(output=args.output, fetch=args.fetch)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(f'状態: {report["status"]}\nレポート: {out / "preparation.md"}')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
