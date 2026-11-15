"""Phase 8 observability/security smoke tests."""
import re

from django.test import TestCase, Client, RequestFactory


class ObservabilityTests(TestCase):
    def test_health_and_metrics(self):
        c = Client()
        r = c.get('/api/health/?deep=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')
        self.assertTrue(r.json()['checks']['database'])
        self.assertTrue(r.json()['checks']['cache'])
        shallow = c.get('/api/health/')
        self.assertEqual(shallow.json()['status'], 'ok')

        r = c.get('/api/metrics/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ('requests', 'cache', 'data_freshness', 'database', 'agent_tools'):
            self.assertIn(key, data)
        self.assertGreaterEqual(data['requests']['total'], 1)

    def test_request_id_header(self):
        r = Client().get('/api/health/', HTTP_X_REQUEST_ID='test-request-123')
        self.assertEqual(r.headers.get('X-Request-ID'), 'test-request-123')
        r2 = Client().get('/api/health/')
        self.assertRegex(r2.headers.get('X-Request-ID', ''), r'^[A-Za-z0-9._-]{8,64}$')

    def test_sensitive_query_redaction(self):
        from core.middleware import redact_path
        req = RequestFactory().get('/api/farmer/profile/?api_key=secret&ok=1&token=abc')
        out = redact_path(req)
        self.assertNotIn('secret', out)
        self.assertNotIn('abc', out)
        self.assertIn('REDACTED', out)
        self.assertIn('ok=1', out)
