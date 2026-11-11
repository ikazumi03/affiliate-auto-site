#!/usr/bin/env python3
"""Draft readiness report only. Article generation is paused for safety.

The previous template reused mobile-plan text for unrelated topics and did not
fetch or verify sources. This command never edits public HTML, ads, sitemap,
topics or Git branches. A reviewed follow-up PR is required to enable generation.
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    topics = json.loads((ROOT / 'ops/topics.json').read_text(encoding='utf-8'))
    report = {
        'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'paused_pending_verified_sources_and_approval',
        'article_generated': False,
        'public_files_changed': False,
        'topics_in_queue': len(topics),
        'sources_verified': False,
        'advertiser_approval_verified': False,
        'blocking_requirements': [
            '承認済み広告案件の状態・確認日・掲載条件を登録する',
            '公式出典の本文を取得し、価格・条件・確認日時の根拠を残す',
            'テーマ別の比較軸で作成し、未確認の価格・体験談を出力しない',
            '未承認PRの重複・既存URLや広告コードの上書きを防ぐ',
            '週1件上限とレビュー必須のPR作成をテストする',
        ],
    }
    md = [
        '# 記事自動生成の準備確認',
        '',
        '**記事の自動生成・PR作成は安全確認のため停止中です。**',
        'この実行では記事・広告・トップページ・サイトマップを変更しません。',
        'AIによる文章生成、出典の事実確認、広告主の提携承認確認は未実装です。',
        f'登録テーマ数: {len(topics)}（採用・承認済みという意味ではありません）',
        '',
        '## 再開前に必要な項目',
    ]
    md.extend('- ' + item for item in report['blocking_requirements'])
    md.extend(['', '公開済み記事の事実・広告条件も、人間による確認が必要です。'])
    out = ROOT / 'reports'
    out.mkdir(exist_ok=True)
    (out / 'draft_readiness.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    text = '\n'.join(md) + '\n'
    (out / 'draft_readiness.md').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
