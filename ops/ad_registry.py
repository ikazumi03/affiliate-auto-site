"""Preparation-only advertiser registry validation; never edits site files."""
import datetime as dt
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs

TRACKING_HOSTS = ('a8.net', 'afi-b.com', 'afb.jp', 'accesstrade.net',
                  'moshimo.com', 'valuecommerce.com', 'linksynergy.com')
OFFICIAL_HOSTS = frozenset({'onsuku.jp', 'faq.onsuku.jp'})
ID = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
SHA = re.compile(r'^[0-9a-f]{64}$')


def tracking_url(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    keys = {k.lower() for k in parse_qs(p.query)}
    return (any(host == h or host.endswith('.' + h) for h in TRACKING_HOSTS)
            or bool(keys & {'a8mat', 'a8ejpredirect', 'aff_id', 'affiliate_id'}))


class AdFragments(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.fragments = []
        self.script = None
        self.script_parts = []
        self.script_recorded = False

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        raw = self.get_starttag_text()
        tracked = (any(tracking_url(data.get(k, '')) for k in ('href', 'src'))
                   or any(k.startswith('data-a8') for k in data))
        if tracked:
            self.fragments.append(raw)
        if tag == 'script':
            self.script = raw
            self.script_parts = []
            self.script_recorded = tracked

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.script is not None:
            self.script_parts.append(data)

    def handle_entityref(self, name):
        if self.script is not None:
            self.script_parts.append('&' + name + ';')

    def handle_charref(self, name):
        if self.script is not None:
            self.script_parts.append('&#' + name + ';')

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            body = ''.join(self.script_parts)
            if not self.script_recorded and re.search(r'a8\.net|a8mat|afi-b\.com', body, re.I):
                self.fragments.append(self.script + body + '</script>')
            self.script = None
            self.script_parts = []


def ad_fingerprint(path):
    parser = AdFragments()
    parser.feed(Path(path).read_text(encoding='utf-8'))
    content = '\n'.join(parser.fragments).encode('utf-8')
    return {'sha256': hashlib.sha256(content).hexdigest(),
            'fragment_count': len(parser.fragments)}


def article_path(root, name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*\.html', name):
        raise ValueError('記事パスは既存のルートHTMLファイル名に限定します')
    p = Path(root) / name
    if p.is_symlink():
        raise ValueError('記事のシンボリックリンクは対象外です')
    p.resolve().relative_to(Path(root).resolve())
    if not p.is_file():
        raise ValueError('台帳に対応する既存記事がありません')
    return p


def valid_date(value):
    try:
        day = dt.date.fromisoformat(value)
        return day <= dt.datetime.now(dt.timezone.utc).date()
    except (TypeError, ValueError):
        return False


def validate_registry(registry, root):
    errors = []
    if not isinstance(registry, dict) or registry.get('schema_version') != 1:
        return ['台帳のschema_versionが不正です']
    state = registry.get('generation_state', {})
    if not isinstance(state, dict):
        return ['generation_stateが不正です']
    for key in ('enabled', 'llm_provider_configured', 'cost_approved'):
        if state.get(key) is not False:
            errors.append(f'準備版では{key}をfalseに固定してください')
    if state.get('publication_mode') != 'human_approved_pull_request':
        errors.append('公開は人間承認PRに限定してください')
    if type(state.get('weekly_limit')) is not int or state['weekly_limit'] != 1:
        errors.append('将来の週次生成上限は1件で指定してください')
    records = registry.get('advertisers')
    if not isinstance(records, list) or not records:
        return errors + ['広告案件の配列がありません']
    ids = set()
    for record in records:
        if not isinstance(record, dict):
            errors.append('広告案件レコードが不正です'); continue
        aid = record.get('id', '')
        if not isinstance(aid, str) or not ID.fullmatch(aid) or aid in ids:
            errors.append('広告案件IDが不正または重複しています'); continue
        ids.add(aid)
        approval = record.get('approval', {})
        conditions = record.get('conditions', {})
        if not isinstance(approval, dict) or approval.get('status') not in ('approved', 'pending', 'unknown', 'suspended'):
            errors.append(f'{aid}: 提携状態が不正です')
        elif approval['status'] == 'approved' and (
                not valid_date(approval.get('confirmed_on'))
                or approval.get('verification_method') not in ('owner_report', 'owner_report_and_screen')
                or approval.get('scope') != 'existing_site'):
            errors.append(f'{aid}: 提携確認日・確認方法・範囲が不正です')
        if not isinstance(conditions, dict) or conditions.get('status') not in ('owner_reviewed', 'pending_recording'):
            errors.append(f'{aid}: 掲載条件の確認状態が不正です')
        elif conditions['status'] == 'owner_reviewed' and (
                not valid_date(conditions.get('confirmed_on')) or not conditions.get('review_scope')):
            errors.append(f'{aid}: 掲載条件の確認日・範囲がありません')
        if record.get('automated_use') not in ('preparation_only', 'blocked_pending_conditions'):
            errors.append(f'{aid}: 準備版の自動利用範囲を超えています')
        assets = record.get('assets')
        if not isinstance(assets, list) or not assets:
            errors.append(f'{aid}: 既存広告の参照がありません'); continue
        for asset in assets:
            try:
                if not isinstance(asset, dict):
                    raise ValueError('広告参照が不正です')
                expected = asset.get('ad_fingerprint', {})
                if (not isinstance(expected, dict) or not isinstance(expected.get('sha256'), str)
                        or not SHA.fullmatch(expected['sha256'])
                        or type(expected.get('fragment_count')) is not int or expected['fragment_count'] < 1):
                    raise ValueError('広告コード指紋が不正です')
                actual = ad_fingerprint(article_path(root, asset.get('article_path')))
                if actual != expected:
                    raise ValueError('既存広告コードの指紋が一致しません。無断で指紋を更新しないでください')
            except (ValueError, OSError, UnicodeError) as exc:
                errors.append(f'{aid}: {exc}')
    return errors


def validate_sources(catalog, registry):
    if not isinstance(catalog, dict) or catalog.get('schema_version') != 1:
        return ['公式出典のschema_versionが不正です']
    sources = catalog.get('sources')
    if not isinstance(sources, list) or not sources:
        return ['公式出典がありません']
    advertiser_ids = {a['id'] for a in registry.get('advertisers', []) if isinstance(a, dict) and 'id' in a}
    errors, ids = [], set()
    for source in sources:
        if not isinstance(source, dict):
            errors.append('公式出典レコードが不正です'); continue
        sid = source.get('id', '')
        if not isinstance(sid, str) or not ID.fullmatch(sid) or sid in ids:
            errors.append('公式出典IDが不正または重複しています'); continue
        ids.add(sid)
        try:
            p = urlsplit(source.get('url', ''))
            valid = (p.scheme == 'https' and p.hostname in OFFICIAL_HOSTS
                     and p.port in (None, 443) and not p.username and not p.password
                     and not p.query and not p.fragment and not tracking_url(source['url']))
        except (TypeError, ValueError, KeyError):
            valid = False
        if not valid:
            errors.append(f'{sid}: 許可済みHTTPS公式URLではありません')
        if source.get('advertiser_id') not in advertiser_ids:
            errors.append(f'{sid}: 広告案件との対応がありません')
        if (type(source.get('max_age_hours')) is not int
                or not 1 <= source['max_age_hours'] <= 168):
            errors.append(f'{sid}: 鮮度上限は1〜168時間で指定してください')
        if source.get('required') is not True:
            errors.append(f'{sid}: 初期試験では必須出典のみ登録してください')
    return errors


def validate_topic(topic, registry, catalog, root):
    if not isinstance(topic, dict):
        return ['試験テーマが不正です']
    errors = []
    if topic.get('mode') != 'update_existing' or topic.get('generation_allowed') is not False:
        errors.append('初期試験は既存記事の取得準備だけに限定します')
    aid = topic.get('advertiser_id')
    record = next((a for a in registry.get('advertisers', []) if a.get('id') == aid), None)
    if record is None:
        return errors + ['試験テーマの広告案件がありません']
    if (record.get('approval', {}).get('status') != 'approved'
            or record.get('conditions', {}).get('status') != 'owner_reviewed'
            or record.get('automated_use') != 'preparation_only'):
        errors.append('試験テーマの提携・掲載条件の確認が不足しています')
    try:
        article_path(root, topic.get('article_path'))
    except (ValueError, OSError) as exc:
        errors.append(str(exc))
    if topic.get('article_path') not in {a.get('article_path') for a in record.get('assets', [])}:
        errors.append('試験記事は広告台帳の既存記事と対応させてください')
    chosen = topic.get('source_ids')
    by_id = {s['id']: s for s in catalog.get('sources', [])}
    if not isinstance(chosen, list) or not chosen or len(chosen) != len(set(chosen)):
        errors.append('試験テーマの出典IDが不足または重複しています')
    else:
        for sid in chosen:
            if sid not in by_id or by_id[sid].get('advertiser_id') != aid:
                errors.append('試験テーマと公式出典の広告案件が一致しません')
    return errors
