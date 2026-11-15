"""Frontend smoke tests — verify pages render and critical DOM hooks exist.

These are structural smoke tests (no browser): they assert that the
served HTML contains the element IDs the JS modules depend on, that
static assets are referenced with cache-busting versions, and that
key JS functions exist in the served files.
"""
import re
from pathlib import Path

from django.test import TestCase
from django.conf import settings

BASE = Path(settings.BASE_DIR)


class ScientificDashboardSmokeTests(TestCase):
    """Smoke tests for /observatory/ (Earth Intelligence)."""

    def setUp(self):
        from farmer.models import FarmerProfile
        f = FarmerProfile.objects.create(name='observer')
        s = self.client.session
        s['farmer_id'] = f.id
        s.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key

    def test_page_200(self):
        r = self.client.get('/observatory/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])

    def test_critical_element_ids_present(self):
        html = self.client.get('/observatory/').content.decode('utf-8')
        # IDs that core/app.js depends on
        for el_id in ['analysis', 'agentQ', 'agentResult', 'climResult',
                      'advResult', 'satMap', 'catalogResults', 'faqResults',
                      'satLegend', 'satOpacity', 'powerChart']:
            self.assertIn(f'id="{el_id}"', html, f'missing #{el_id}')

    def test_static_assets_referenced(self):
        html = self.client.get('/observatory/').content.decode('utf-8')
        self.assertIn('app.js', html)
        self.assertIn('app.css', html)
        self.assertIn('tokens.css', html)
        # cache-busting version param
        self.assertRegex(html, r'app\.js[^"\']*\?v=\d+')

    def test_i18n_files_exist(self):
        for lang in ('fa', 'en'):
            p = BASE / 'core' / 'static' / 'shared' / 'i18n' / f'{lang}.json'
            self.assertTrue(p.exists(), f'missing {p}')
            self.assertGreater(p.stat().st_size, 100)

    def test_app_js_has_key_functions(self):
        js = (BASE / 'core' / 'static' / 'core' / 'app.js').read_text(encoding='utf-8')
        for fn in ['renderAnalysis', 'loadI18n', 'applyLanguage', 'initMap']:
            self.assertIn(fn, js, f'missing function {fn}')


class LandingPageSmokeTests(TestCase):
    """Smoke tests for / (platform landing page)."""

    def test_landing_page_200(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        html = r.content.decode('utf-8')
        self.assertIn('Understand Earth. Make Better Decisions.', html)
        self.assertIn('hero-earth', html)
        self.assertIn('/observatory/', html)
        self.assertIn('/farmer/', html)
        self.assertIn('landing.css', html)
        self.assertIn('landing.js', html)

    def test_landing_assets_exist(self):
        landing_dir = BASE / 'core' / 'static' / 'shared' / 'images' / 'landing'
        for name in ['hero-earth.jpg', 'earth-intelligence.jpg',
                     'farmer-assistant.jpg', 'climate-monitoring.jpg',
                     'data-analysis.jpg', 'smart-agriculture.jpg']:
            self.assertTrue((landing_dir / name).exists(), f'missing {name}')

    def test_landing_i18n_files_exist(self):
        for name in ('landing_en.json', 'landing_fa.json'):
            p = BASE / 'core' / 'static' / 'shared' / 'i18n' / name
            self.assertTrue(p.exists(), f'missing {p}')
            self.assertGreater(p.stat().st_size, 1000)


class FarmerDashboardSmokeTests(TestCase):
    """Smoke tests for /farmer/."""

    def test_page_200(self):
        r = self.client.get('/farmer/')
        self.assertEqual(r.status_code, 200)

    def test_critical_element_ids_present(self):
        html = self.client.get('/farmer/').content.decode('utf-8')
        for el_id in ['content', 'offlineBanner', 'app', 'main']:
            self.assertIn(f'id="{el_id}"', html, f'missing #{el_id}')

    def test_static_assets_referenced(self):
        html = self.client.get('/farmer/').content.decode('utf-8')
        self.assertIn('farmer.js', html)
        self.assertIn('farmer.css', html)
        self.assertIn('tokens.css', html)
        self.assertRegex(html, r'farmer\.js[^"\']*\?v=\d+')

    def test_farmer_js_has_key_functions(self):
        js = (BASE / 'farmer' / 'static' / 'farmer' / 'farmer.js').read_text(encoding='utf-8')
        for fn in ['renderToday', 'loadRecommendations', 'loadAlerts',
                   'renderRisks', 'sendChat', 'switchTab']:
            self.assertIn(fn, js, f'missing function {fn}')
        # chat input + map are rendered dynamically by JS
        self.assertIn('chatIn', js)
        self.assertIn('leaflet', js.lower())

    def test_leaflet_lazy_loaded(self):
        js = (BASE / 'farmer' / 'static' / 'farmer' / 'farmer.js').read_text(encoding='utf-8')
        # Leaflet should be loaded dynamically, not in initial HTML
        html = self.client.get('/farmer/').content.decode('utf-8')
        self.assertNotIn('leaflet.js', html.split('</head>')[0] + '</head>')
        self.assertIn('leaflet', js.lower())


class JsSyntaxTests(TestCase):
    """Validate all static JS files parse correctly (node --check)."""

    JS_FILES = [
        'core/static/core/app.js',
        'core/static/core/landing.js',
        'core/static/core/auth.js',
        'core/static/core/workspace.js',
        'core/static/shared/i18n.js',
        'farmer/static/farmer/farmer.js',
        'farmer/static/farmer/i18n.js',
    ]

    def test_js_syntax(self):
        import shutil, subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('node not available')
        for rel in self.JS_FILES:
            p = BASE / rel
            if not p.exists():
                continue
            r = subprocess.run([node, '--check', str(p)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0,
                             f'{rel} syntax error: {r.stderr[:300]}')

    def test_workspace_js_functions(self):
        js = (BASE / 'core' / 'static' / 'core' / 'workspace.js').read_text(encoding='utf-8')
        for fn in ['loadAnalyses', 'wsSave', 'tsRun', 'reproduceAnalysis',
                   'deleteAnalysis', 'wsApi']:
            self.assertIn(fn, js, f'missing {fn}')

    def test_app_js_workspace_hook(self):
        js = (BASE / 'core' / 'static' / 'core' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('loadAnalyses', js)
        self.assertIn('satSplitMode', js)
