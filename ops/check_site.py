#!/usr/bin/env python3
"""Free, dependency-free site operations audit. No credentials required."""
import argparse, datetime as dt, html.parser, json, pathlib, re, urllib.parse, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST')
class Parser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.title=''; self.description=False; self.has_h1=False; self.disclosure=False; self.text=[]; self._title=False; self._h1=False
    def handle_starttag(self,t,a):
        attrs=dict(a)
        if t=='a' and attrs.get('href'): self.links.append(attrs['href'])
        if t in ('script','link','img') and attrs.get('src'): self.links.append(attrs['src'])
        if t=='link' and attrs.get('href'): self.links.append(attrs['href'])
        if t=='title': self._title=True
        if t=='h1': self.has_h1=True
        if t=='meta' and attrs.get('name','').lower()=='description' and attrs.get('content'): self.description=True
    def handle_endtag(self,t):
        if t=='title': self._title=False
    def handle_data(self,d):
        if self._title: self.title+=d
        self.text.append(d)

def fetch_status(url):
    req=urllib.request.Request(url,headers={'User-Agent':'KurashiSiteAudit/1.0 (+site-owner)'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r: return int(r.status),None
    except urllib.error.HTTPError as e: return int(e.code),str(e)
    except Exception as e: return None,str(e)[:200]

def run(site_url=None):
    issues=[]; alerts=[]; counts={'pages':0,'external_links':0,'affiliate_slots_configured':0}
    pages=sorted(ROOT.glob('*.html')); counts['pages']=len(pages)
    existing={p.name for p in ROOT.iterdir() if p.is_file()}
    external=set()
    for p in pages:
        data=p.read_text(encoding='utf-8'); parser=Parser(); parser.feed(data)
        if not parser.title.strip(): issues.append(f'{p.name}: titleタグなし')
        if not parser.description: issues.append(f'{p.name}: meta descriptionなし')
        if not parser.has_h1: issues.append(f'{p.name}: h1見出しなし')
        content=' '.join(parser.text)
        if not re.search('アフィリエイト|広告',content): issues.append(f'{p.name}: 広告開示文が見つかりません')
        for link in parser.links:
            if link.startswith(('mailto:','tel:','javascript:','#','data:')): continue
            parsed=urllib.parse.urlsplit(link)
            if parsed.scheme in ('http','https'): external.add(link); continue
            path=urllib.parse.unquote(parsed.path).lstrip('/')
            if path and path not in existing: issues.append(f'{p.name}: 内部リンク先がない → {path}')
    slots=ROOT/'affiliate-links.js'
    if slots.exists():
        text=slots.read_text(encoding='utf-8'); counts['affiliate_slots_configured']=len(re.findall(r'^\s*[a-z_]+:\s*[\'\"]https?://',text,re.M))
        if counts['affiliate_slots_configured']==0: alerts.append('広告URLが未設定です。提携承認後、許可されたリンク形式で設定してください。')
    if site_url:
        code,error=fetch_status(site_url.rstrip('/')+'/')
        if code!=200: issues.append(f'公開サイト: 応答HTTP {code or "接続失敗"} ({error or ""})')
        for url in sorted(external):
            code,error=fetch_status(url)
            if code in (404,410): issues.append(f'外部リンク: HTTP {code} → {url}')
            elif code is None or code in (403,429,500,502,503): alerts.append(f'外部リンク要確認 (自動判定不可): HTTP {code} → {url}')
    else: alerts.append('SITE_URLが未設定のため公開サイトの応答チェックは省略')
    counts['external_links']=len(external)
    report={'checked_at':TODAY,'site_url':site_url,'summary':counts,'issues':sorted(set(issues)),'notes':sorted(set(alerts))}
    out=ROOT/'reports'; out.mkdir(exist_ok=True)
    (out/'latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    md=['# サイト自動点検レポート',f'点検日時: {TODAY}',f'対象URL: {site_url or "未設定（ローカル検査）"}',f'ページ数: {len(pages)} / 広告URL設定: {counts["affiliate_slots_configured"]}件',f'\n## 要対応 ({len(report["issues"])}件)']
    md += ['- '+x for x in report['issues']] or ['- 現時点で重大な検知なし']
    md += ['\n## 注意・未設定']+(['- '+x for x in report['notes']] or ['- なし'])
    md += ['\n## 運用メモ','- ASPの管理画面データ・収益・Google検索順位は、この点検だけでは取得できません。','- 403・429などはブロックの可能性があり、リンク切れと断定しません。','- 数字・キャンペーン・法的表記の正確性は別途人が確認してください。']
    (out/'latest.md').write_text('\n'.join(md)+'\n',encoding='utf8')
    print('\n'.join(md))
    return len(report['issues'])
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--site-url',default=''); args=ap.parse_args()
    run(args.site_url or None)
