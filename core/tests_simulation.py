"""Simulated user journeys — public pages + farmer workflow + agent chat.

External data engines are mocked so the suite is deterministic and offline.
"""
import json
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, Client

from farmer.models import FarmerProfile, Farm, Field, CropProfile, CropCycle, FarmObservation


class PublicJourneySimulationTests(TestCase):
    def test_landing_observatory_farmer_and_health(self):
        c = Client()
        for path in ('/', '/observatory/', '/farmer/', '/api/health/', '/api/metrics/'):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn('text/html' if path in ('/', '/observatory/', '/farmer/') else 'application/json',
                          r['Content-Type'])
        html = c.get('/').content.decode('utf-8')
        self.assertIn('Understand Earth. Make Better Decisions.', html)
        self.assertIn('/observatory/', html)
        self.assertIn('/farmer/', html)

    def test_scientific_agent_requires_account_and_stays_safe(self):
        f = FarmerProfile.objects.create(name='scientist')
        c = Client()
        s = c.session
        s['farmer_id'] = f.id
        s.save()
        c.cookies[settings.SESSION_COOKIE_NAME] = s.session_key
        anon = Client().get('/api/agent/', {'q': 'سلام چطوری'})
        self.assertEqual(anon.status_code, 401)
        r = c.get('/api/agent/', {'q': 'سلام چطوری'})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get('intent'), 'unknown')
        self.assertTrue(data.get('limitations'))


class FarmerJourneySimulationTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.farmer = None
        self.farm = None
        self.field = None

    def _auth(self):
        return {'HTTP_X_FARMER_KEY': self.farmer.api_key}

    def _post(self, path, payload):
        return self.c.post(path, data=json.dumps(payload), content_type='application/json', **self._auth())

    def test_full_farmer_journey(self):
        # 1) onboarding
        r = self.c.post('/api/farmer/profile/', data=json.dumps({'name': 'کاربر آزمایشی'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.farmer = FarmerProfile.objects.get(id=r.json()['farmer']['id'])

        # 2) farm + field + crop + cycle
        r = self._post('/api/farmer/farms/create/', {'name': 'مزرعه تست', 'province': 'تهران'})
        self.assertEqual(r.status_code, 201)
        self.farm = Farm.objects.get(id=r.json()['farm']['id'])

        r = self._post('/api/farmer/fields/create/', {
            'farm_id': self.farm.id, 'name': 'قطعه اصلی', 'lat': None, 'lon': None,
            'area_ha': 3.0, 'soil_type': 'loam', 'irrigation_method': 'drip'})
        self.assertEqual(r.status_code, 201)
        self.field = Field.objects.get(id=r.json()['field']['id'])

        CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0, gdd_total=None)
        r = self._post('/api/farmer/cycles/create/', {
            'field_id': self.field.id, 'crop': 'wheat', 'planting_date': '2026-10-01'})
        self.assertEqual(r.status_code, 201)

        # 3) expense for economics
        r = self._post('/api/farmer/expenses/create/', {
            'farm_id': self.farm.id, 'category': 'water', 'amount': 1200, 'date': '2026-11-01'})
        self.assertEqual(r.status_code, 201)

        # 4) agent conversation — engines mocked, orchestration real
        fake_irrigation = {'advice_fa': 'آبیاری را امروز انجام دهید.', 'data_sources': ['FAO-56'],
                           'limitations_fa': ['rule-based']}
        fake_lifecycle = {'crop_name_fa': 'گندم', 'growth_stage': 'رشد رویشی', 'progress': 0.4,
                          'estimated_harvest': '2027-05-01', 'current_stage': {'name_fa': 'رشد رویشی'},
                          'data_sources': ['NASA POWER → GDD'], 'limitations': []}
        fake_recommend = {'ranking': [{'name_fa': 'گندم', 'score': 91}], 'data_sources': ['x'], 'limitations': []}
        fake_risks = {'field_id': self.field.id, 'field_name': self.field.name, 'risks': []}
        fake_catalog = {'source': 'NASA Earthdata CMR', 'hits': 1,
                        'items': [{'title': 'Fake Dataset', 'short_name': 'FAKE'}],
                        'data_sources': ['NASA Earthdata CMR'],
                        'limitations': ['metadata only']}

        with patch('farmer.services.tools.get_irrigation_advice', return_value=fake_irrigation), \
             patch('farmer.services.tools.get_lifecycle', return_value=fake_lifecycle), \
             patch('farmer.services.tools.recommend_crops', return_value=fake_recommend), \
             patch('farmer.services.tools.assess_field_risks', return_value=[]), \
             patch('farmer.services.tools.search_collections', return_value={'items': fake_catalog['items'], 'hits': 1}):

            r = self._post('/api/farmer/agent/', {'question': 'امروز چه کار کنم؟', 'mode': 'expert'})
            self.assertEqual(r.status_code, 200)
            d = r.json()
            self.assertEqual(d.get('intent'), 'daily')
            self.assertIn('expert', d)

            r = self._post('/api/farmer/agent/', {'question': 'چه محصولی بکارم؟'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get('intent'), 'recommend')
            self.assertIn('گندم', r.json().get('answer_fa', ''))

            r = self._post('/api/farmer/agent/', {'question': 'آبیاری چقدر؟'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get('intent'), 'irrigation')
            self.assertIn('آبیاری', r.json().get('answer_fa', ''))

            r = self._post('/api/farmer/agent/', {'question': 'برداشت کیه؟'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get('intent'), 'lifecycle')
            self.assertIn('گندم', r.json().get('answer_fa', ''))

            r = self._post('/api/farmer/agent/', {'question': 'هزینه‌ها چقدر؟'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get('intent'), 'economics')
            self.assertIn('هزینه کل مزرعه', r.json().get('answer_fa', ''))

            r = self._post('/api/farmer/agent/', {'question': 'چه خطراتی هست؟'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get('intent'), 'risk')

            r = self._post('/api/farmer/agent/', {'question': 'جستجوی مجموعه داده ماهواره‌ای'})
            self.assertEqual(r.status_code, 200)
            self.assertIn(r.json().get('resolved_intent'), ('satellite_search', 'scientific_research'))

            # 5) mutating agent action requires confirmation, then executes once
            r = self._post('/api/farmer/agent/', {'question': 'ثبت مشاهده: برگ‌ها سالم هستند'})
            self.assertEqual(r.status_code, 200)
            d = r.json()
            self.assertTrue(d.get('confirmation_required'))
            self.assertEqual(FarmObservation.objects.count(), 0)

            r = self._post('/api/farmer/agent/tool/', {
                'tool': d['tool'], 'params': d['params'], 'confirm': True,
                'field_id': d['params'].get('field_id')})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(FarmObservation.objects.count(), 1)

            # 6) unknown question stays honest
            r = self._post('/api/farmer/agent/', {'question': 'سلام چطوری'})
            self.assertEqual(r.status_code, 200)
            self.assertIn('suggestions', r.json())
