from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops'))
import source_fetch


class SourceDataGuards(unittest.TestCase):
    def test_empty_or_script_only_body_is_rejected(self):
        url = 'https://onsuku.jp/plan_guidance'
        for body in (b'', b'<html><head><title>Test</title></head><body><script>1</script></body></html>'):
            results = [(b'', 'https://onsuku.jp/robots.txt', 404, 'text/plain', 'utf-8'),
                       (body, url, 200, 'text/html', 'utf-8')]
            with patch.object(source_fetch, '_read', side_effect=results):
                with self.assertRaises(source_fetch.SourceError):
                    source_fetch.fetch_source({'id': 'onsuku-pricing', 'url': url})

    def test_invalid_encoding_is_rejected_not_replaced(self):
        url = 'https://onsuku.jp/plan_guidance'
        results = [(b'', 'https://onsuku.jp/robots.txt', 404, 'text/plain', 'utf-8'),
                   (b'price:\xff', url, 200, 'text/plain', 'utf-8')]
        with patch.object(source_fetch, '_read', side_effect=results):
            with self.assertRaises(source_fetch.SourceError):
                source_fetch.fetch_source({'id': 'onsuku-pricing', 'url': url})


if __name__ == '__main__':
    unittest.main()
