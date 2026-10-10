import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mirror', Path(__file__).resolve().parents[1] / 'scripts/sync_google_site.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.mirror = m.Mirror(Path(self.temporary.name))

    def test_demo_link_stays_under_project_base(self):
        result = self.mirror.local_url('https://lacam-autostore-demo.gain-salvo-0t.chatgpt.site/horse.html?embed=1#view', m.CONFIG['sources'][0]['url'], 'index.html')
        self.assertEqual(result, 'interactive/autostore/horse.html?embed=1#view')

    def test_home_link_from_demo_is_relative(self):
        result = self.mirror.local_url(m.CONFIG['sources'][0]['url'], m.CONFIG['sources'][2]['url'], 'interactive/autostore/index.html')
        self.assertEqual(result, '../../index.html')

    def test_scene_navigation_is_crawled_but_translation_keys_are_not(self):
        code = "const SCENES = [['horse.html','Horse']]; const PAGE_EN={'missing.html':['Other']};"
        self.assertEqual(m.references(code, '.js'), ['horse.html'])

    def test_missing_dependencies_prevent_publish(self):
        self.mirror.files = {'index.html': b'<p>Robotics</p><button id="motion-toggle"></button><script src="missing.js"></script>'}
        with self.assertRaisesRegex(RuntimeError, 'Broken local links'):
            self.mirror.publish()
        self.assertFalse((Path(self.temporary.name) / 'index.html').exists())

    def test_external_runtime_prevents_publish(self):
        self.mirror.files = {'index.html': b'<p>Robotics</p><button id="motion-toggle"></button><iframe src="https://sites.google.com/view/example"></iframe>'}
        with self.assertRaisesRegex(RuntimeError, 'External runtime dependencies'):
            self.mirror.validate()

    def test_root_relative_scene_paths_are_rewritten(self):
        base = m.CONFIG['sources'][1]['url']
        text = "const SCENES = [['/scenes/horse.html','Horse']];"
        result = m.ROOT_FILE.sub(lambda match: match[1] + self.mirror.local_url(match[2], base, 'interactive/construction/index.html') + match[1], text)
        self.assertIn("['scenes/horse.html'", result)

    def test_edge_script_removed_without_removing_app(self):
        text = '<script src="app.js"></script><script>(function(){window.__CF$cv$params={};})()</script>'
        self.assertEqual(m.CF_SCRIPT.sub('', text), '<script src="app.js"></script>')

    def test_reject_reserved_managed_path(self):
        for path in ['../index.html', '.git/config', 'scripts/sync_google_site.py']:
            with self.assertRaises(ValueError):
                m.safe_path(path)

if __name__ == '__main__':
    unittest.main()
