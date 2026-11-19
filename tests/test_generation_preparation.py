import copy
import datetime as dt
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ops'))
from ad_registry import ad_fingerprint, validate_registry, validate_sources, validate_topic
from prepare_generation import run, evidence_is_fresh


def public_files(root):
    return {p.name: p.read_bytes() for p in root.iterdir()
            if p.is_file() and p.suffix in {'.html', '.js', '.css', '.xml', '.txt'}}


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'site'
        self.root.mkdir()
        (self.root / 'ops').mkdir()
        for p in REPO.iterdir():
            if p.is_file() and p.suffix in {'.html', '.js', '.css', '.xml', '.txt'}:
                shutil.copy2(p, self.root / p.name)
        for name in ('affiliate_registry.json', 'official_sources.json', 'pilot_topic.json'):
            shutil.copy2(REPO / 'ops' / name, self.root / 'ops' / name)
        self.registry = self.read('affiliate_registry.json')
        self.sources = self.read('official_sources.json')
        self.topic = self.read('pilot_topic.json')

    def tearDown(self):
        self.temp.cleanup()

    def read(self, name):
        return json.loads((self.root / 'ops' / name).read_text())

    def save(self, name, value):
        (self.root / 'ops' / name).write_text(json.dumps(value, ensure_ascii=False) + '\n')

    def test_seed_registry_and_onsuku_topic_valid(self):
        self.assertEqual(validate_registry(self.registry, self.root), [])
        self.assertEqual(validate_sources(self.sources, self.registry), [])
        self.assertEqual(validate_topic(self.topic, self.registry, self.sources, self.root), [])
        self.assertEqual(len(self.registry['advertisers']), 5)
        self.assertEqual(sum(a['conditions']['status'] == 'pending_recording' for a in self.registry['advertisers']), 4)

    def test_offline_run_never_calls_network_or_changes_public(self):
        before = public_files(self.root)
        config = {p.name: p.read_bytes() for p in (self.root / 'ops').iterdir()}
        with patch('source_fetch.fetch_source') as fetch:
            report, code, out = run(self.root, self.base / 'out')
            fetch.assert_not_called()
        self.assertEqual(code, 0)
        self.assertFalse(report['article_generated'])
        self.assertFalse(report['pr_created'])
        self.assertFalse(report['llm_api_called'])
        self.assertFalse(report['facts_verified'])
        self.assertEqual(public_files(self.root), before)
        self.assertEqual(config, {p.name: p.read_bytes() for p in (self.root / 'ops').iterdir()})
        self.assertTrue((out / 'preparation.json').is_file())

    def test_changed_ad_code_blocks_preparation(self):
        p = self.root / 'onsuku.html'
        p.write_text(p.read_text().replace('4BGFJE', 'CHANGED'))
        self.assertTrue(validate_registry(self.registry, self.root))
        with patch('source_fetch.fetch_source') as fetch:
            report, code, _ = run(self.root, self.base / 'out', fetch=True)
            fetch.assert_not_called()
        self.assertEqual(code, 2)
        self.assertTrue(report['errors'])

    def test_pending_conditions_block_selected_topic(self):
        self.registry['advertisers'][0]['conditions']['status'] = 'pending_recording'
        self.assertTrue(validate_topic(self.topic, self.registry, self.sources, self.root))

    def test_unapproved_advertiser_blocks_selected_topic(self):
        self.registry['advertisers'][0]['approval']['status'] = 'pending'
        self.assertTrue(validate_topic(self.topic, self.registry, self.sources, self.root))

    def test_duplicate_ids_are_rejected(self):
        self.registry['advertisers'].append(copy.deepcopy(self.registry['advertisers'][0]))
        self.assertTrue(validate_registry(self.registry, self.root))
        self.sources['sources'].append(copy.deepcopy(self.sources['sources'][0]))
        self.assertTrue(validate_sources(self.sources, self.registry))

    def test_non_official_and_tracking_sources_rejected(self):
        for url in ('http://onsuku.jp/plan_guidance', 'https://px.a8.net/svt/ejp?a8mat=x',
                    'https://onsuku.jp.evil.invalid/', 'https://127.0.0.1/',
                    'https://secret@onsuku.jp/', 'https://onsuku.jp/?affiliate_id=x'):
            data = copy.deepcopy(self.sources)
            data['sources'][0]['url'] = url
            self.assertTrue(validate_sources(data, self.registry), url)

    def test_path_traversal_or_new_article_is_rejected(self):
        for name in ('../onsuku.html', '/tmp/new.html', 'new.html'):
            topic = copy.deepcopy(self.topic)
            topic['article_path'] = name
            self.assertTrue(validate_topic(topic, self.registry, self.sources, self.root))
        topic = copy.deepcopy(self.topic)
        topic['mode'] = 'create_new'
        self.assertTrue(validate_topic(topic, self.registry, self.sources, self.root))

    def test_setting_enable_or_cost_flags_does_not_activate_generation(self):
        for key in ('enabled', 'llm_provider_configured', 'cost_approved'):
            registry = copy.deepcopy(self.registry)
            registry['generation_state'][key] = True
            self.assertTrue(validate_registry(registry, self.root))

    def test_freshness_rejects_old_or_future_timestamp(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.assertTrue(evidence_is_fresh({'fetched_at': now.isoformat()}, 24, now))
        for stamp in ((now - dt.timedelta(hours=25)).isoformat(),
                      (now + dt.timedelta(minutes=1)).isoformat(), 'invalid', '2026-11-12T00:00:00'):
            self.assertFalse(evidence_is_fresh({'fetched_at': stamp}, 24, now))

    def test_failed_source_stops_without_article_or_cached_fallback(self):
        from source_fetch import SourceError
        with patch('source_fetch.fetch_source', side_effect=SourceError('robots denied')) as fetch:
            report, code, out = run(self.root, self.base / 'out', fetch=True)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(code, 3)
        self.assertEqual(report['sources'], [])
        self.assertFalse(report['article_generated'])
        self.assertEqual(list(out.glob('evidence-*.json')), [])

    def test_successful_mock_fetch_is_not_fact_verification(self):
        def mock(source):
            return {'id': source['id'], 'requested_url': source['url'], 'final_url': source['url'],
                    'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'content_sha256': 'a' * 64, 'text_sha256': 'b' * 64, 'text': '公式本文のテスト',
                    'http_status': 200, 'robots_checked': True,
                    'fact_verification': 'not_performed', 'trusted_for_instructions': False}
        before = public_files(self.root)
        with patch('source_fetch.fetch_source', side_effect=mock):
            report, code, out = run(self.root, self.base / 'out', fetch=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(report['sources']), 2)
        self.assertFalse(report['facts_verified'])
        self.assertFalse(report['article_generated'])
        self.assertEqual(len(list(out.glob('evidence-*.json'))), 2)
        self.assertEqual(public_files(self.root), before)

    def test_output_inside_repo_or_nonempty_folder_is_rejected(self):
        with self.assertRaises(ValueError):
            run(self.root, self.root / 'reports')
        out = self.base / 'out'
        out.mkdir(); (out / 'old.json').write_text('{}')
        with self.assertRaises(ValueError):
            run(self.root, out)

    def test_workflow_is_manual_readonly_and_without_secrets(self):
        text = (REPO / '.github/workflows/generation-preparation.yml').read_text()
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('contents: read', text)
        self.assertIn('default: false', text)
        for value in ('schedule:', 'contents: write', 'pull-requests: write',
                      'git push', 'gh pr create', 'secrets.'):
            self.assertNotIn(value, text)


if __name__ == '__main__':
    unittest.main()
