import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / 'ops' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.iterdir()
            if p.is_file() and p.suffix in {'.html', '.js', '.css', '.xml', '.txt'}}


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for p in REPO.iterdir():
            if p.is_file() and p.suffix in {'.html', '.js', '.css', '.xml', '.txt'}:
                shutil.copy2(p, self.root / p.name)
        (self.root / 'ops').mkdir()
        shutil.copy2(REPO / 'ops/topics.json', self.root / 'ops/topics.json')
        self.audit = load('check_site')
        self.audit.ROOT = self.root
        self.draft = load('generate_draft')
        self.draft.ROOT = self.root

    def tearDown(self):
        self.temp.cleanup()

    def test_local_audit_never_changes_public_files(self):
        before = public_files(self.root)
        self.audit.run(skip_external=True)
        self.assertEqual(before, public_files(self.root))
        report = json.loads((self.root / 'reports/latest.json').read_text())
        self.assertFalse(report['compliance_checked'])
        self.assertTrue(any('ネットワーク点検は実行していません' in n for n in report['notes']))

    def test_live_inventory_never_requests_ad_urls(self):
        before = public_files(self.root)
        seen = []
        def fake(url):
            seen.append(url)
            self.assertFalse(self.audit.is_tracking_url(url))
            return url, 200, None
        with patch.object(self.audit, 'fetch_url', side_effect=fake):
            self.audit.run()
        self.assertTrue(seen)
        self.assertEqual(before, public_files(self.root))
        report = json.loads((self.root / 'reports/latest.json').read_text())
        self.assertGreaterEqual(report['summary']['tracking_urls_not_requested'], 17)

    def test_tracker_and_protocol_relative_url_are_blocked(self):
        with patch.object(self.audit.urllib.request, 'build_opener') as opener:
            self.audit.fetch_url('https://px.a8.net/svt/ejp?a8mat=test')
            opener.assert_not_called()
        self.assertTrue(self.audit.is_tracking_url('//statics.a8.net/ad/ad.js'))
        with self.assertRaises(self.audit.urllib.error.URLError):
            self.audit.SafeRedirect().redirect_request(None, None, 302, '', {}, 'https://px.a8.net/click')

    def test_paused_draft_never_changes_public_or_topics(self):
        before = public_files(self.root)
        topics = (self.root / 'ops/topics.json').read_bytes()
        self.draft.main()
        self.assertEqual(before, public_files(self.root))
        self.assertEqual(topics, (self.root / 'ops/topics.json').read_bytes())
        report = json.loads((self.root / 'reports/draft_readiness.json').read_text())
        self.assertFalse(report['article_generated'])
        self.assertFalse(report['sources_verified'])

    def test_script_only_disclosure_and_bad_canonical_not_certified(self):
        (self.root / 'fixture.html').write_text('<html><head><title>Test</title><meta name="description" content="Test"><link rel="canonical" href="javascript:bad"></head><body><h1>Test</h1><script>const x="広告";</script></body></html>')
        self.audit.run(skip_external=True)
        report = json.loads((self.root / 'reports/latest.json').read_text())
        self.assertTrue(any('fixture.html: canonical' in n for n in report['seo_notices']))
        self.assertTrue(any('fixture.html: 広告開示文' in n for n in report['seo_notices']))
        md = (self.root / 'reports/latest.md').read_text()
        self.assertNotIn('規約違反等の不備は検知されませんでした', md)

    def test_detected_issues_retained_in_report(self):
        (self.root / 'broken.html').write_text('<html><h1>Test</h1></html>')
        issues = self.audit.run(skip_external=True)
        self.assertGreater(issues, 0)
        report = json.loads((self.root / 'reports/latest.json').read_text())
        self.assertTrue(report['issues'])

    def test_workflows_cannot_push_production(self):
        for name in ('weekly-audit.yml', 'weekly-draft-pr.yml'):
            workflow = (REPO / '.github/workflows' / name).read_text()
            self.assertIn('contents: read', workflow)
            self.assertNotIn('git push', workflow)
            self.assertNotIn('git commit', workflow)
            self.assertNotIn('gh pr create', workflow)
        draft = (REPO / '.github/workflows/weekly-draft-pr.yml').read_text()
        self.assertNotIn('schedule:', draft)


if __name__ == '__main__':
    unittest.main()
