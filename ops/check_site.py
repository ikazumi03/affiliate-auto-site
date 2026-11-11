#!/usr/bin/env python3
"""Read-only technical site audit. Writes reports only, never public assets.

No factual/regulatory/advertiser approval certification is performed. Affiliate
tracking URLs are inventoried but not requested, to avoid artificial ad events.
"""
import argparse
import concurrent.futures
import datetime as dt
import html.parser
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SITE_URL = 'https://affiliate-auto-site-1tk.pages.dev'
TRACKING_DOMAINS = (
    'a8.net', 'afi-b.com', 'afb.jp', 'accesstrade.net',
    'moshimo.com', 'valuecommerce.com', 'linksynergy.com',
)


def is_tracking_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    query_keys = {key.lower() for key in urllib.parse.parse_qs(parsed.query)}
    return (any(host == domain or host.endswith('.' + domain)
                for domain in TRACKING_DOMAINS)
            or bool(query_keys & {'a8mat', 'a8ejpredirect', 'aff_id', 'affiliate_id'}))


class HTMLInspector(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ad_links = set()
        self.title = ''
        self.description = False
        self.h1_count = 0
        self.canonical = None
        self.text = []
        self._title = False
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag in ('script', 'style'):
            self._hidden += 1
        if tag == 'title':
            self._title = True
        if tag == 'h1':
            self.h1_count += 1
        if tag == 'meta' and data.get('name', '').lower() == 'description':
            self.description = bool(data.get('content', '').strip())
        if tag == 'link' and data.get('rel') == 'canonical':
            self.canonical = data.get('href')
        value = data.get('href') if tag in ('a', 'link') else data.get('src') if tag in ('script', 'img') else None
        if value:
            self.links.append(value)
            if tag == 'a' and 'sponsored' in data.get('rel', '').split():
                self.ad_links.add(value)

    def handle_endtag(self, tag):
        if tag == 'title':
            self._title = False
        if tag in ('script', 'style'):
            self._hidden = max(0, self._hidden - 1)

    def handle_data(self, text):
        if self._title:
            self.title += text
        if not self._hidden:
            self.text.append(text)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if is_tracking_url(newurl):
            raise urllib.error.URLError('広告計測URLへのリダイレクトは点検対象外')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url, timeout=10):
    if is_tracking_url(url):
        return url, None, '広告計測URLはリクエストしません'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'KurashiSiteAudit/3.0 (+https://affiliate-auto-site-1tk.pages.dev)'})
    try:
        with urllib.request.build_opener(SafeRedirect()).open(req, timeout=timeout) as response:
            return url, int(response.status), None
    except urllib.error.HTTPError as error:
        return url, error.code, str(error.reason)
    except Exception as error:
        return url, None, str(error)[:160]


def run(site_url=DEFAULT_SITE_URL, skip_external=False):
    base = site_url.rstrip('/') if site_url else ''
    site_host = urllib.parse.urlsplit(base).netloc
    issues, notices, notes = [], [], []
    pages = [p for p in sorted(ROOT.glob('*.html')) if not p.name.startswith('google')]
    external, tracking, published = set(), set(), set()
    for page in pages:
        parser = HTMLInspector()
        parser.feed(page.read_text(encoding='utf-8'))
        if not parser.title.strip():
            issues.append(f'{page.name}: titleタグが空または未設定')
        if not parser.description:
            issues.append(f'{page.name}: meta descriptionが空または未設定')
        if parser.h1_count != 1:
            notices.append(f'{page.name}: H1見出しは{parser.h1_count}件です（通常は1件）')
        expected = base + ('/' if page.name == 'index.html' else '/' + page.name)
        if base and parser.canonical != expected:
            notices.append(f'{page.name}: canonicalが想定URLと一致しません → {expected}')
        if not re.search(r'アフィリエイト|広告|【PR】', ' '.join(parser.text)):
            notices.append(f'{page.name}: 広告開示文の文字列が見つかりません（表示上の適切さは人間確認）')
        if base:
            published.add(expected)
        for original in parser.links:
            if original.startswith(('mailto:', 'tel:', 'javascript:', '#', 'data:')):
                continue
            link = 'https:' + original if original.startswith('//') else original
            parsed = urllib.parse.urlsplit(link)
            if is_tracking_url(link) or original in parser.ad_links:
                tracking.add(link)
                continue
            if parsed.scheme in ('http', 'https') and parsed.netloc != site_host:
                external.add(link)
                continue
            path = urllib.parse.unquote(parsed.path).lstrip('/')
            target = ROOT / (path or 'index.html')
            try:
                target.resolve().relative_to(ROOT.resolve())
                if not target.is_file():
                    issues.append(f'{page.name}: 内部リンク先がありません → {path}')
            except ValueError:
                issues.append(f'{page.name}: リポジトリ外への内部リンク → {path}')
    slots = ROOT / 'affiliate-links.js'
    slot_count = 0
    if slots.exists():
        text = slots.read_text(encoding='utf-8')
        slot_count = len(re.findall(r'\b[a-z_]+\s*:\s*[\'\"]https?://', text))
        if not slot_count:
            notes.append('affiliate-links.jsの共通広告URLは未設定。既存HTML内の広告コードの有無・承認状態とは別です。')
    notes.append(f'広告・計測用URL {len(tracking)}件は通信しません。案件終了・計測動作・素材表示は人間確認が必要です。')
    if skip_external or not base:
        notes.append('ネットワーク点検は実行していません。')
    else:
        urls = sorted(published | external)
        print(f'公開ページ・非広告URLを点検: {len(urls)}件（広告URLへのアクセスなし）', flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for url, code, error in pool.map(fetch_url, urls):
                if code in (404, 410):
                    issues.append(f'HTTP {code} → {url}')
                elif code is None or not 200 <= code < 300:
                    notes.append(f'自動確認できません (HTTP {code}): {url} ({error or ""})')
    report = {
        'checked_at': dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST'),
        'site_url': site_url,
        'summary': {'pages': len(pages), 'external_links': len(external),
                    'tracking_urls_not_requested': len(tracking),
                    'affiliate_slots_configured': slot_count},
        'issues': sorted(set(issues)), 'seo_notices': sorted(set(notices)),
        'notes': sorted(set(notes)),
        'compliance_checked': False, 'facts_checked': False,
        'advertiser_approval_checked': False, 'public_files_changed': False,
    }
    md = [
        '# サイト自動点検レポート',
        f'点検日時: {report["checked_at"]}', f'対象URL: {site_url or "ローカルのみ"}',
        f'ページ数: {len(pages)} / 非広告の外部URL数: {len(external)} / 広告URL（通信しない）: {len(tracking)}',
        '', '**本番ファイル・広告コード・サイトマップは更新しません。**',
        '本レポートは技術点検です。価格の正確さ、法令・ASP規約適合、提携承認を判定しません。',
    ]
    for title, key, empty in (
        ('要対応・技術的な検知', 'issues', '実施範囲では技術的な問題を検知していません。'),
        ('SEO・マークアップ確認', 'seo_notices', '検査した項目の不足は検知していません。検索順位・全SEO項目の保証ではありません。'),
        ('注意・ステータス', 'notes', 'なし'),
    ):
        md.extend(['', f'## {title} ({len(report[key])}件)'])
        md.extend('- ' + item for item in (report[key] or [empty]))
    md.extend(['', '## 運用メモ',
               '- HTTP 200でも表示内容・計測成功を保証しません。403/429/タイムアウトはリンク切れと断定しません。',
               '- 価格・キャンペーン・広告主の掲載条件は公式情報とASP画面で別途確認してください。',
               '- 記事自動生成は安全確認のため停止中です。準備確認ワークフローの成功は記事作成成功を意味しません。'])
    out = ROOT / 'reports'
    out.mkdir(exist_ok=True)
    (out / 'latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    text = '\n'.join(md) + '\n'
    (out / 'latest.md').write_text(text, encoding='utf-8')
    print(text)
    return len(issues)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-url', default=DEFAULT_SITE_URL)
    ap.add_argument('--skip-external', action='store_true')
    args = ap.parse_args()
    # レポートをIssueへ届けてから、Workflowの最終ステップで異常件数を判定する。
    run(site_url=args.site_url, skip_external=args.skip_external)
