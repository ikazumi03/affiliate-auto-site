#!/usr/bin/env python3
"""
くらしの選び方ガイド - サイト自動点検・SEO監査スクリプト v2
- 高速並行HTTPリクエストによる外部リンク・公開サイト点検
- プロトコル相対URL (//...) の適切な外部リンク判定
- canonical / title / meta description / h1 / 広告開示の完全チェック
- sitemap.xml の自動生成・更新
- GitHub Actions Step Summary / Issue 形式のレポート出力
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
TODAY_JST = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))
TODAY_STR = TODAY_JST.strftime('%Y-%m-%d %H:%M JST')
TODAY_ISO = TODAY_JST.strftime('%Y-%m-%d')

DEFAULT_SITE_URL = "https://affiliate-auto-site-1tk.pages.dev"

class HTMLInspector(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.title = ''
        self.description = False
        self.has_h1 = False
        self.canonical = None
        self.has_ldjson = False
        self.text = []
        self._in_title = False
        self._in_script_ldjson = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'a' and d.get('href'):
            self.links.append(d['href'])
        elif tag in ('script', 'img') and d.get('src'):
            self.links.append(d['src'])
        elif tag == 'link':
            if d.get('href'):
                self.links.append(d['href'])
            if d.get('rel') == 'canonical':
                self.canonical = d.get('href')
        elif tag == 'title':
            self._in_title = True
        elif tag == 'h1':
            self.has_h1 = True
        elif tag == 'meta' and d.get('name', '').lower() == 'description' and d.get('content'):
            self.description = True
        elif tag == 'script' and d.get('type') == 'application/ld+json':
            self.has_ldjson = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.text.append(data)


def fetch_url(url, timeout=10):
    """URLのステータスコードをチェック（User-Agent偽装）"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; KurashiSiteAudit/2.0; +https://affiliate-auto-site-1tk.pages.dev)'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return url, int(r.status), None
    except urllib.error.HTTPError as e:
        return url, int(e.code), str(e.reason)
    except Exception as e:
        return url, None, str(e)[:160]


def update_sitemap(site_url, pages):
    """sitemap.xml を全HTMLページから自動生成"""
    base = site_url.rstrip('/')
    urls_xml = []
    for p in sorted(pages):
        name = p.name
        # 404やプライベートファイル等を除外
        if name.startswith('google') or name.startswith('.'):
            continue
        loc = f"{base}/" if name == 'index.html' else f"{base}/{name}"
        urls_xml.append(f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{TODAY_ISO}</lastmod>\n    <changefreq>weekly</changefreq>\n  </url>")
    
    sitemap_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + '\n'.join(urls_xml) + '\n'
        '</urlset>\n'
    )
    (ROOT / 'sitemap.xml').write_text(sitemap_content, encoding='utf-8')


def run(site_url=DEFAULT_SITE_URL, skip_external=False, generate_sitemap=True):
    issues = []
    alerts = []
    seo_notices = []
    counts = {'pages': 0, 'external_links': 0, 'affiliate_slots_configured': 0}

    pages = sorted(ROOT.glob('*.html'))
    # 除外（MacゴミファイルやGoogle認証ファイル）
    target_pages = [p for p in pages if not p.name.startswith('google')]
    counts['pages'] = len(target_pages)
    existing_files = {p.name for p in ROOT.iterdir() if p.is_file()}

    external_links = set()

    for p in target_pages:
        data = p.read_text(encoding='utf-8', errors='ignore')
        inspector = HTMLInspector()
        inspector.feed(data)

        if not inspector.title.strip():
            issues.append(f'{p.name}: titleタグが空または未設定')
        if not inspector.description:
            issues.append(f'{p.name}: meta descriptionが未設定')
        if not inspector.has_h1:
            issues.append(f'{p.name}: h1見出しが未設定')
        
        # canonical チェック
        if not inspector.canonical:
            seo_notices.append(f'{p.name}: canonicalタグが未設定')

        content = ' '.join(inspector.text)
        if not re.search('アフィリエイト|広告', content):
            issues.append(f'{p.name}: 広告開示文（PR/広告明記）が見つかりません')

        for link in inspector.links:
            if link.startswith(('mailto:', 'tel:', 'javascript:', '#', 'data:')):
                continue
            # プロトコル相対URL (//...)
            if link.startswith('//'):
                link = 'https:' + link

            parsed = urllib.parse.urlsplit(link)
            if parsed.scheme in ('http', 'https'):
                external_links.add(link)
                continue

            path = urllib.parse.unquote(parsed.path).lstrip('/')
            if path and path not in existing_files:
                issues.append(f'{p.name}: 内部リンク先が存在しません → {path}')

    # 広告スロット設定の点検
    slots = ROOT / 'affiliate-links.js'
    if slots.exists():
        text = slots.read_text(encoding='utf-8')
        counts['affiliate_slots_configured'] = len(re.findall(r'^\s*[a-z_]+:\s*[\'\"]https?://', text, re.M))
        if counts['affiliate_slots_configured'] == 0:
            alerts.append('affiliate-links.jsの共通広告URLが未設定です（承認後に正規リンクを設定可能）。')

    # sitemap.xml 更新
    if generate_sitemap and site_url:
        update_sitemap(site_url, target_pages)

    # 外部URL・サイト本体のHTTP並行点検
    if site_url and not skip_external:
        print(f"[*] 公開サイトおよび外部リンクを並行チェック中... ({len(external_links)}件)")
        urls_to_check = [site_url.rstrip('/') + '/'] + sorted(external_links)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(fetch_url, u): u for u in urls_to_check}
            for future in concurrent.futures.as_completed(future_to_url):
                url, code, error = future.result()
                if url == site_url.rstrip('/') + '/':
                    if code != 200:
                        issues.append(f'本番サイト応答異常: HTTP {code or "接続失敗"} ({error or ""})')
                else:
                    if code in (404, 410):
                        issues.append(f'外部リンク切れ (404/410): HTTP {code} → {url}')
                    elif code is None or code in (403, 429, 500, 502, 503):
                        alerts.append(f'外部リンク応答確認推奨 (HTTP {code}): {url}')

    counts['external_links'] = len(external_links)

    report = {
        'checked_at': TODAY_STR,
        'site_url': site_url,
        'summary': counts,
        'issues': sorted(set(issues)),
        'seo_notices': sorted(set(seo_notices)),
        'notes': sorted(set(alerts))
    }

    out = ROOT / 'reports'
    out.mkdir(exist_ok=True)
    (out / 'latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    md = [
        '# サイト自動点検レポート',
        f'- **点検日時**: {TODAY_STR}',
        f'- **対象URL**: [{site_url}]({site_url})' if site_url else '- **対象URL**: 未設定（ローカル検査）',
        f'- **総ページ数**: {counts["pages"]} ページ',
        f'- **外部・広告リンク数**: {counts["external_links"]} 件',
        f'- **affiliate-links.js 設定数**: {counts["affiliate_slots_configured"]} 件',
        '',
        f'## 🚨 要対応・重大な検知 ({len(report["issues"])}件)',
    ]
    if report['issues']:
        md += [f'- {x}' for x in report['issues']]
    else:
        md.append('- 重大なリンク切れや規約違反等の不備は検知されませんでした。正常です。')

    md += [
        '',
        f'## 🔍 SEO・マークアップ確認 ({len(report["seo_notices"])}件)',
    ]
    if report['seo_notices']:
        md += [f'- {x}' for x in report['seo_notices']]
    else:
        md.append('- 全ページのcanonicalタグ等が正常に設定されています。')

    md += [
        '',
        f'## ℹ️ 注意・ステータス ({len(report["notes"])}件)',
    ]
    if report['notes']:
        md += [f'- {x}' for x in report['notes']]
    else:
        md.append('- 特筆すべき注意事項はありません。')

    md += [
        '',
        '## 📝 運用メモ',
        '- HTTP 403/429 等は相手先サーバーのBot遮断の可能性があり、直ちにリンク切れとは断定しません。',
        '- 商品の最新価格・キャンペーン・終了条件は週1回の人間確認で最終確認してください。',
        '- 新規記事の下書きはPull Requestとして提案されます。確認後マージでCloudflare Pagesに反映されます。'
    ]

    report_text = '\n'.join(md) + '\n'
    (out / 'latest.md').write_text(report_text, encoding='utf-8')
    print(report_text)
    return len(report['issues'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-url', default=DEFAULT_SITE_URL)
    ap.add_argument('--skip-external', action='store_true')
    args = ap.parse_args()
    run(site_url=args.site_url, skip_external=args.skip_external)
