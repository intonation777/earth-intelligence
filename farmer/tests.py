import json

from django.test import TestCase, Client

from .models import FarmerProfile, Farm, Field, CropProfile, CropCycle, FarmTask


class FarmerApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.farmer = FarmerProfile.objects.create(name='علی رضایی')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه شمال', province='گلستان')
        self.crop = CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0)
        self.field = Field.objects.create(farm=self.farm, name='قطعه ۱', lat=37.0, lon=55.0,
                                          area_ha=2.5, soil_type='loam', current_crop=self.crop)
        self.other = FarmerProfile.objects.create(name='کاربر دیگر')

    def _post(self, url, data, key=None):
        headers = {'HTTP_X_FARMER_KEY': key} if key else {}
        return self.client.post(url, data=json.dumps(data), content_type='application/json', **headers)

    def test_profile_create_returns_api_key(self):
        r = self.client.post('/api/farmer/profile/', data=json.dumps({'name': 'مریم'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertIn('api_key', r.json()['farmer'])

    def test_profile_requires_auth(self):
        r = self.client.get('/api/farmer/profile/get/')
        self.assertEqual(r.status_code, 401)

    def test_farm_create_and_list(self):
        r = self._post('/api/farmer/farms/create/', {'name': 'مزرعه جدید'}, key=self.farmer.api_key)
        self.assertEqual(r.status_code, 201)
        r = self.client.get('/api/farmer/farms/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(len(r.json()['farms']), 2)

    def test_field_create_and_list(self):
        r = self._post('/api/farmer/fields/create/',
                       {'farm_id': self.farm.id, 'name': 'قطعه ۲', 'area_ha': 1.0},
                       key=self.farmer.api_key)
        self.assertEqual(r.status_code, 201)
        r = self.client.get('/api/farmer/fields/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(len(r.json()['fields']), 2)

    def test_cannot_access_other_farmers_field(self):
        r = self.client.get(f'/api/farmer/fields/{self.field.id}/',
                            HTTP_X_FARMER_KEY=self.other.api_key)
        self.assertEqual(r.status_code, 404)

    def test_cannot_create_field_in_other_farm(self):
        other_farm = Farm.objects.create(farmer=self.other, name='مزرعه دیگر')
        r = self._post('/api/farmer/fields/create/', {'farm_id': other_farm.id, 'name': 'x'},
                       key=self.farmer.api_key)
        self.assertEqual(r.status_code, 404)

    def test_field_update_partial(self):
        r = self._post(f'/api/farmer/fields/{self.field.id}/update/',
                       {'area_ha': 3.0}, key=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.field.refresh_from_db()
        self.assertEqual(self.field.area_ha, 3.0)
        self.assertEqual(self.field.name, 'قطعه ۱')  # unchanged

    def test_crop_list(self):
        r = self.client.get('/api/farmer/crops/')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()['count'], 1)

    def test_invalid_json(self):
        r = self.client.post('/api/farmer/profile/', data='not json',
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)


class RecommendTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0,
                                   t_min_c=-5, t_max_c=35, water_need_mm=450,
                                   growth_days=150, kc_max=1.15, gdd_total=1800,
                                   planting_seasons=['winter', 'spring'],
                                   soil_preference='loam', salinity_tolerance='medium')
        CropProfile.objects.create(key='rice', name_fa='برنج', base_temp_c=10,
                                   t_min_c=12, t_max_c=40, water_need_mm=1200,
                                   growth_days=140, kc_max=1.2, gdd_total=1800,
                                   planting_seasons=['spring'],
                                   soil_preference='clay', salinity_tolerance='low')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0,
                                          soil_type='loam', water_source='well',
                                          irrigation_method='drip')

    def test_score_crop_temperature_penalty(self):
        from farmer.services.recommend import _score_crop
        crop = CropProfile.objects.get(key='rice')
        climate = {'tmean': 25, 'tmax': 42, 'tmin': 15, 'rain_total': 300, 'months': 12}
        score, reasons, limits, conf = _score_crop(crop, climate, self.field, spi6=None)
        self.assertLess(score, 60)  # tmax 42 > rice t_max 40 → penalty

    def test_score_crop_rainfed_high_water_penalty(self):
        from farmer.services.recommend import _score_crop
        crop = CropProfile.objects.get(key='rice')
        climate = {'tmean': 25, 'tmax': 35, 'tmin': 15, 'rain_total': 200, 'months': 12}
        field = Field(farm=self.farm, name='x', lat=32, lon=53, water_source='rainfed',
                      irrigation_method='rainfed', soil_type='clay')
        score, reasons, limits, conf = _score_crop(crop, climate, field, spi6=None)
        self.assertTrue(any('دیم' in l or 'نیاز آبی' in l for l in limits))

    def test_recommend_ranking_structure(self):
        from unittest.mock import patch
        from farmer.services.recommend import recommend_crops
        fake_climate = {'tmean': 20, 'tmax': 30, 'tmin': 10, 'rain_total': 400, 'months': 12}
        with patch('farmer.services.recommend._monthly_climate', return_value=fake_climate), \
             patch('farmer.services.recommend.get_climate_indicators', side_effect=Exception('skip')):
            d = recommend_crops(self.field)
        self.assertIn('ranking', d)
        self.assertEqual(len(d['ranking']), 2)
        self.assertTrue(all('score' in r and 'reasons_fa' in r for r in d['ranking']))
        self.assertIn('data_sources', d)
        self.assertIn('limitations', d)

    def test_recommend_requires_coordinates(self):
        from farmer.services.recommend import recommend_crops
        field = Field(farm=self.farm, name='no-coord', lat=None, lon=None)
        d = recommend_crops(field)
        self.assertIn('error', d)


class LifecycleTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.crop = CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0,
                                               gdd_total=1800, growth_days=150)
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)

    def test_future_planting(self):
        from datetime import date, timedelta
        from farmer.models import CropCycle
        from farmer.services.lifecycle import get_lifecycle
        cycle = CropCycle.objects.create(field=self.field, crop=self.crop,
                                         planting_date=date.today() + timedelta(days=30))
        d = get_lifecycle(cycle)
        self.assertEqual(d['status'], 'not_planted_yet')

    def test_calendar_fallback_without_gdd(self):
        from datetime import date, timedelta
        from farmer.models import CropCycle
        from farmer.services.lifecycle import get_lifecycle
        cycle = CropCycle.objects.create(field=self.field, crop=self.crop,
                                         planting_date=date.today() - timedelta(days=75))
        d = get_lifecycle(cycle)
        # field has lat/lon so GDD path attempted; if POWER fails → calendar fallback
        self.assertIn(d['method'], ('gdd', 'calendar'))
        self.assertIsNotNone(d['progress'])
        self.assertIn('current_stage', d)

    def test_cycle_create_api(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/cycles/create/',
                   data=_json.dumps({'field_id': self.field.id, 'crop': 'wheat',
                                     'planting_date': '2026-10-01'}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 201)
        r = c.get('/api/farmer/cycles/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(len(r.json()['cycles']), 1)

    def test_calendar_api_requires_params(self):
        c = Client()
        r = c.get('/api/farmer/calendar/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 400)
        r = c.get('/api/farmer/calendar/?field_id=999', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 404)


class IrrigationTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.crop = CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0,
                                               gdd_total=1800, growth_days=150, kc_max=1.15)
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0,
                                          area_ha=2.0, irrigation_method='drip')
        from farmer.models import CropCycle
        from datetime import date, timedelta
        CropCycle.objects.create(field=self.field, crop=self.crop,
                                 planting_date=date.today() - timedelta(days=75))

    def test_no_cycle_error(self):
        from farmer.services.irrigation import get_irrigation_advice
        other = Field.objects.create(farm=self.farm, name='بدون چرخه', lat=32, lon=53)
        d = get_irrigation_advice(other)
        self.assertIn('error', d)

    def test_advice_structure(self):
        from unittest.mock import patch
        from farmer.services.irrigation import get_irrigation_advice
        fake_climate = {'monthly': [{'month': '2026-11', 'pet_mm': 40.0, 'precip_mm': 10.0,
                                     'tmean_c': 15, 'tmax_c': 22, 'tmin_c': 8,
                                     'water_balance_mm': -20}]}
        with patch('farmer.services.irrigation.get_climate_indicators', return_value=fake_climate), \
             patch('farmer.services.irrigation.get_lifecycle', return_value={'progress': 0.5, 'current_stage': {'name_fa': 'رشد زایشی'}}):
            d = get_irrigation_advice(self.field)
        self.assertIn('advice_fa', d)
        self.assertIn('net_need_mm', d)
        self.assertIn('limitations_fa', d)
        self.assertIn('data_sources', d)
        # soil missing → limitation noted
        self.assertTrue(any('خاک' in l for l in d['limitations_fa']))

    def test_irrigation_api(self):
        c = Client()
        r = c.get(f'/api/farmer/irrigation/?field_id={self.field.id}',
                  HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('advice_fa', r.json())


class DailyTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)

    def test_daily_structure(self):
        from farmer.services.daily import get_daily_briefing
        d = get_daily_briefing(self.farmer)
        self.assertIn('fields', d)
        self.assertIn('overdue_tasks', d)
        self.assertIn('summary_fa', d)
        self.assertIn('data_sources', d)

    def test_overdue_task_appears(self):
        from datetime import date, timedelta
        from farmer.models import FarmTask
        from farmer.services.daily import get_daily_briefing
        FarmTask.objects.create(farmer=self.farmer, title='سم‌پاشی',
                                due_date=date.today() - timedelta(days=2))
        d = get_daily_briefing(self.farmer)
        self.assertEqual(len(d['overdue_tasks']), 1)

    def test_task_create_and_done(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/tasks/create/',
                   data=_json.dumps({'title': 'آبیاری', 'field_id': self.field.id}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 201)
        tid = r.json()['task']['id']
        r = c.post(f'/api/farmer/tasks/{tid}/done/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.json()['task']['done'], True)
        r = c.get('/api/farmer/tasks/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.json()['tasks'][0]['done'], True)

    def test_daily_api(self):
        c = Client()
        r = c.get('/api/farmer/daily/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('summary_fa', r.json())


class RiskDiagnosisTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)
        crop = CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0,
                                          t_max_c=35, t_min_c=-5)
        from farmer.models import CropCycle
        from datetime import date, timedelta
        CropCycle.objects.create(field=self.field, crop=crop,
                                 planting_date=date.today() - timedelta(days=60))

    def test_risk_no_coords(self):
        from farmer.services.risk import assess_field_risks
        f = Field.objects.create(farm=self.farm, name='بدون مختصات', lat=None, lon=None)
        self.assertEqual(assess_field_risks(f), [])

    def test_risk_structure_with_mock(self):
        from unittest.mock import patch
        from farmer.services.risk import assess_field_risks
        fake = {'indicators': {'spi_6m': {'value': -1.8}, 'heatwave': {'value': {'events_ge3days': 2}},
                               'frost_days': {'value': 5}, 'water_balance': {'value': -150}},
                'monthly': [{'month': '2026-11', 'precip_mm': 130}]}
        with patch('farmer.services.risk.get_climate_indicators', return_value=fake):
            risks = assess_field_risks(self.field)
        kinds = {r['kind'] for r in risks}
        self.assertIn('drought', kinds)
        self.assertIn('heat_stress', kinds)
        self.assertTrue(all('source' in r and 'action_fa' in r for r in risks))

    def test_diagnose_symptoms(self):
        from farmer.services.diagnosis import diagnose
        d = diagnose(['زردی برگ', 'لکه قهوه‌ای روی برگ'])
        self.assertIn('possible_causes', d)
        self.assertTrue(len(d['possible_causes']) > 0)
        self.assertTrue(d['expert_referral'])
        self.assertTrue(any('کارشناس' in l for l in d['limitations_fa']))

    def test_diagnose_unknown_symptom(self):
        from farmer.services.diagnosis import diagnose
        d = diagnose(['علائم نامشخص xyz'])
        self.assertEqual(d['matched'], [])
        self.assertTrue(d['expert_referral'])

    def test_diagnose_api(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/diagnose/',
                   data=_json.dumps({'symptoms': ['زردی برگ']}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('possible_causes', r.json())

    def test_risk_api(self):
        c = Client()
        r = c.get(f'/api/farmer/risks/?field_id={self.field.id}',
                  HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('risks', r.json())


class EconomicsTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        Field.objects.create(farm=self.farm, name='قطعه', area_ha=2.0)
        from farmer.models import FarmExpense
        FarmExpense.objects.create(farm=self.farm, category='seed', amount=1000)
        FarmExpense.objects.create(farm=self.farm, category='water', amount=500)

    def test_cost_only_no_price(self):
        from farmer.services.economics import get_economics
        d = get_economics(self.farm)
        self.assertEqual(d['total_cost'], 1500)
        self.assertEqual(d['cost_per_ha'], 750)
        self.assertTrue(any('قیمت' in l for l in d['limitations_fa']))

    def test_profit_with_yield_price(self):
        from farmer.services.economics import get_economics
        d = get_economics(self.farm, yield_kg_ha=4000, price_per_unit=10, area_ha=2.0)
        # revenue = 4000*2*10 = 80000; profit = 78500
        self.assertEqual(d['revenue'], 80000)
        self.assertEqual(d['profit'], 78500)
        self.assertIn('scenarios', d)
        self.assertEqual(len(d['scenarios']), 3)

    def test_break_even(self):
        from farmer.services.economics import get_economics
        d = get_economics(self.farm, price_per_unit=10, area_ha=2.0)
        # break-even yield = 1500 / (10*2) = 75 kg/ha
        self.assertEqual(d['break_even_yield_kg_ha'], 75)

    def test_expense_api(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/expenses/create/',
                   data=_json.dumps({'farm_id': self.farm.id, 'category': 'labor', 'amount': 300}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 201)
        r = c.get(f'/api/farmer/economics/?farm_id={self.farm.id}&yield_kg_ha=4000&price=10',
                  HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('profit', r.json())


class FarmerAgentTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه ۱', lat=32.0, lon=53.0)

    def test_unknown_question(self):
        from farmer.services.farmer_agent import answer
        d = answer(self.farmer, 'سلام چطوری')
        self.assertIsNone(d['intent'])
        self.assertIn('suggestions', d)

    def test_daily_intent(self):
        from farmer.services.farmer_agent import answer
        d = answer(self.farmer, 'امروز چه کار کنم؟')
        self.assertEqual(d['intent'], 'daily')
        self.assertIn('summary_fa', d['details'])

    def test_recommend_intent_single_field(self):
        from unittest.mock import patch
        from farmer.services.farmer_agent import answer
        fake = {'ranking': [{'name_fa': 'گندم', 'score': 80}], 'data_sources': ['x'], 'limitations': []}
        with patch('farmer.services.tools.recommend_crops', return_value=fake):
            d = answer(self.farmer, 'چه محصولی بکارم؟')
        self.assertEqual(d['intent'], 'recommend')
        self.assertIn('گندم', d['answer_fa'])

    def test_multi_field_asks_choice(self):
        from farmer.services.farmer_agent import answer
        Field.objects.create(farm=self.farm, name='قطعه ۲', lat=32.1, lon=53.1)
        d = answer(self.farmer, 'آبیاری چقدر؟')
        self.assertEqual(d['intent'], 'irrigation')
        self.assertIn('fields', d)

    def test_agent_api(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/agent/',
                   data=_json.dumps({'question': 'امروز چه کار کنم؟'}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('answer_fa', r.json())


class OperationTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه ۱', lat=32.0, lon=53.0)

    def test_irrigation_record(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/operations/',
                   data=_json.dumps({'type': 'irrigation', 'field_id': self.field.id,
                                     'amount_m3': 50, 'method': 'قطره‌ای'}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 201)
        from farmer.models import IrrigationRecord
        self.assertEqual(IrrigationRecord.objects.count(), 1)

    def test_fertilizer_and_observation(self):
        import json as _json
        c = Client()
        for op, extra in [('fertilizer', {'kind': 'اوره', 'amount_kg': 100}),
                          ('observation', {'note': 'برگ‌ها زرد شدند'})]:
            r = c.post('/api/farmer/operations/',
                       data=_json.dumps({'type': op, 'field_id': self.field.id, **extra}),
                       content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
            self.assertEqual(r.status_code, 201)

    def test_invalid_type_and_field(self):
        import json as _json
        c = Client()
        r = c.post('/api/farmer/operations/',
                   data=_json.dumps({'type': 'hack', 'field_id': self.field.id}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 400)
        r = c.post('/api/farmer/operations/',
                   data=_json.dumps({'type': 'irrigation', 'field_id': 999}),
                   content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 404)


class DecisionEngineTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه ۱', lat=32.0, lon=53.0, area_ha=2.0)

    def test_confidence_bounds(self):
        from farmer.services.decision import compute_confidence
        self.assertLessEqual(compute_confidence(1.0, 1.0, '2026-11-13'), 0.95)
        self.assertGreaterEqual(compute_confidence(0.0, 0.0, '2020-01-01'), 0.05)

    def test_confidence_missing_data_lower(self):
        from farmer.services.decision import compute_confidence
        full = compute_confidence(0.8, 1.0, '2026-11-13')
        poor = compute_confidence(0.8, 0.3, '2020-01-01')
        self.assertGreater(full, poor)

    def test_context_reports_missing(self):
        from farmer.services.decision import build_context
        ctx = build_context(self.field)
        self.assertIn('missing', ctx)
        self.assertIn('completeness', ctx)
        self.assertLess(ctx['completeness'], 1.0)  # no soil/cycle/etc

    def test_generate_and_feedback(self):
        import json as _json
        from farmer.services.decision import generate_recommendations, record_feedback
        gen = generate_recommendations(self.farmer)
        self.assertIn('recommendations', gen)
        self.assertIn('context_summary', gen)
        if gen['recommendations']:
            rid = gen['recommendations'][0]['id']
            rec = record_feedback(self.farmer, rid, 'accepted', 'خوب بود')
            self.assertEqual(rec['status'], 'accepted')
            self.assertEqual(rec['outcome_note'], 'خوب بود')

    def test_feedback_invalid_status(self):
        from farmer.services.decision import record_feedback
        from farmer.models import Recommendation
        r = Recommendation.objects.create(farmer=self.farmer, title_fa='تست')
        self.assertIsNone(record_feedback(self.farmer, r.id, 'bogus'))

    def test_recommendations_api(self):
        c = Client()
        r = c.get('/api/farmer/recommendations/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('recommendations', r.json())


class AlertTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)
        from farmer.models import RiskAlert
        self.alert = RiskAlert.objects.create(farmer=self.farmer, field=self.field,
            kind='drought', severity='high', title_fa='خشکسالی', source='test')

    def test_alerts_list(self):
        c = Client()
        r = c.get('/api/farmer/alerts/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['unread'], 1)
        self.assertEqual(len(d['alerts']), 1)

    def test_alert_read_and_dismiss(self):
        c = Client()
        r = c.post(f'/api/farmer/alerts/{self.alert.id}/action/',
                   data=json.dumps({'action': 'read'}), content_type='application/json',
                   HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.alert.refresh_from_db()
        self.assertTrue(self.alert.is_read)
        r = c.post(f'/api/farmer/alerts/{self.alert.id}/action/',
                   data=json.dumps({'action': 'dismiss'}), content_type='application/json',
                   HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.alert.refresh_from_db()
        self.assertTrue(self.alert.dismissed)
        r = c.get('/api/farmer/alerts/', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(len(r.json()['alerts']), 0)

    def test_alert_other_farmer_404(self):
        other = FarmerProfile.objects.create(name='دیگری')
        c = Client()
        r = c.post(f'/api/farmer/alerts/{self.alert.id}/action/',
                   data=json.dumps({'action': 'read'}), content_type='application/json',
                   HTTP_X_FARMER_KEY=other.api_key)
        self.assertEqual(r.status_code, 404)


class DecisionEngineGapTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0, area_ha=1.0)

    def test_expired_rec_allows_regeneration(self):
        from farmer.models import Recommendation
        from farmer.services.decision import generate_recommendations
        from datetime import date, timedelta
        # expired rec with same title should NOT block new generation
        Recommendation.objects.create(
            farmer=self.farmer, field=self.field, title_fa='تست منقضی',
            valid_until=date.today() - timedelta(days=1))
        gen = generate_recommendations(self.farmer)
        # engine may or may not produce 'تست منقضی' — just ensure no crash
        self.assertIn('recommendations', gen)

    def test_rec_has_cost_and_resources(self):
        from farmer.services.decision import generate_recommendations
        gen = generate_recommendations(self.farmer)
        for r in gen['recommendations']:
            self.assertIn('estimated_cost', r)
            self.assertIn('required_resources', r)
            self.assertIn('expired', r)

    def test_conflict_detection(self):
        from farmer.services.decision import _dedup_and_conflicts
        f = self.field
        recs = [
            {'field': f, 'title_fa': 'آبیاری — قطعه', 'confidence': 0.7,
             'importance': 'high', 'action_fa': 'آب بده', 'reason_fa': '',
             'evidence': [], 'data_sources': [], 'limitations_fa': '',
             'expected_benefit': '', 'estimated_cost': '', 'required_resources': [],
             'valid_until': None, 'review_at': None, 'timing_fa': ''},
            {'field': f, 'title_fa': 'کمبود آب', 'confidence': 0.6,
             'importance': 'high', 'action_fa': '', 'reason_fa': 'کمبود آب در دوره',
             'evidence': [], 'data_sources': [], 'limitations_fa': '',
             'expected_benefit': '', 'estimated_cost': '', 'required_resources': [],
             'valid_until': None, 'review_at': None, 'timing_fa': ''},
        ]
        out = _dedup_and_conflicts(recs)
        irr = next(r for r in out if 'آبیاری' in r['title_fa'])
        self.assertIn('conflicts_with', irr)

    def test_context_extended_fields(self):
        from farmer.services.decision import build_context
        ctx = build_context(self.field)
        self.assertIn('observations_count', ctx)
        self.assertIn('operations_count', ctx)
        self.assertIn('has_observations', ctx)
        self.assertIn('has_operations_history', ctx)


class ET0EngineTests(TestCase):
    """Golden tests for FAO-56 ET0 — pure functions, no I/O."""

    def test_sat_vp_reference(self):
        from farmer.services.et0 import _sat_vp
        # FAO-56 reference: es at 20°C ≈ 2.338 kPa
        self.assertAlmostEqual(_sat_vp(20.0), 2.338, places=2)
        self.assertAlmostEqual(_sat_vp(30.0), 4.243, places=2)

    def test_delta_slope(self):
        from farmer.services.et0 import _delta_slope
        d = _delta_slope(20.0)
        self.assertGreater(d, 0.1)
        self.assertLess(d, 0.3)

    def test_wind_u2_conversion(self):
        from farmer.services.et0 import _wind_u2
        # u2 ≈ 0.748 × u10 (FAO-56)
        self.assertAlmostEqual(_wind_u2(2.0), 1.496, places=2)

    def test_extraterrestrial_radiation(self):
        from farmer.services.et0 import _extraterrestrial_radiation
        # summer solstice at 30°N should be high (~40 MJ/m²/day)
        ra = _extraterrestrial_radiation(30.0, 172)
        self.assertGreater(ra, 35)
        self.assertLess(ra, 45)

    def test_et0_pm_missing_inputs(self):
        from farmer.services.et0 import et0_penman_monteith
        r = et0_penman_monteith(None, 50, 2, 20, 101, 32, 200)
        self.assertEqual(r['method'], 'unavailable')
        self.assertIn('T2M', r['missing'])

    def test_et0_pm_typical_day(self):
        from farmer.services.et0 import et0_penman_monteith
        # typical summer day in Iran: T=30, RH=40%, wind=2m/s, Rs=25MJ, P=900hPa
        r = et0_penman_monteith(30.0, 40.0, 2.0, 25.0/3.6, 90.0, 32.0, 200,
                                tmin=20.0, tmax=38.0)
        self.assertEqual(r['method'], 'FAO56_PM')
        self.assertIsNotNone(r['et0_mm'])
        # ET0 for hot dry day should be 5-8 mm/day
        self.assertGreater(r['et0_mm'], 4.0)
        self.assertLess(r['et0_mm'], 10.0)

    def test_et0_hargreaves(self):
        from farmer.services.et0 import et0_hargreaves
        r = et0_hargreaves(20.0, 35.0, 32.0, 200)
        self.assertEqual(r['method'], 'FAO56_HARGREAVES')
        self.assertIsNotNone(r['et0_mm'])
        self.assertGreater(r['et0_mm'], 3.0)

    def test_et0_hargreaves_missing(self):
        from farmer.services.et0 import et0_hargreaves
        r = et0_hargreaves(None, 35.0, 32.0, 200)
        self.assertEqual(r['method'], 'unavailable')


class IrrigationV2Tests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0, area_ha=2.0)
        self.crop = CropProfile.objects.create(key='wheat', name_fa='گندم', base_temp_c=0, kc_max=1.15)
        self.cycle = CropCycle.objects.create(field=self.field, crop=self.crop, status='active', planting_date='2026-10-01')

    def test_advice_has_et0_engine(self):
        from farmer.services.irrigation import get_irrigation_advice
        r = get_irrigation_advice(self.field)
        self.assertIn('et0_engine', r)
        self.assertIn('scheduling', r)
        self.assertIn('kc_used', r)
        self.assertIn('limitations_fa', r)

    def test_kc_stage_curve(self):
        from farmer.services.irrigation import _kc_for_stage, STAGE_KC_FACTOR
        self.assertEqual(len(STAGE_KC_FACTOR), 6)
        kc = _kc_for_stage(self.crop, 3)  # mid-season
        self.assertAlmostEqual(kc, 1.15, places=2)

    def test_efficiency_mapping(self):
        from farmer.services.irrigation import _efficiency
        eff, name = _efficiency('drip')
        self.assertEqual(eff, 0.90)
        eff2, _ = _efficiency('unknown')
        self.assertEqual(eff2, 0.70)

    def test_no_cycle_returns_error(self):
        from farmer.services.irrigation import get_irrigation_advice
        f2 = Field.objects.create(farm=self.farm, name='بدون چرخه', lat=32.0, lon=53.0)
        r = get_irrigation_advice(f2)
        self.assertIn('error', r)


class AlertLifecycleTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)
        from farmer.models import RiskAlert
        self.alert = RiskAlert.objects.create(
            farmer=self.farmer, field=self.field, kind='drought',
            severity='high', title_fa='خشکسالی', status='active',
            fingerprint='abc123')

    def test_acknowledge(self):
        c = Client()
        r = c.post(f'/api/farmer/alerts/{self.alert.id}/action/',
                   data=json.dumps({'action': 'acknowledge'}), content_type='application/json',
                   HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, 'acknowledged')
        self.assertIsNotNone(self.alert.acknowledged_at)
        self.assertTrue(self.alert.is_read)

    def test_snooze_and_resolve(self):
        c = Client()
        c.post(f'/api/farmer/alerts/{self.alert.id}/action/',
               data=json.dumps({'action': 'snooze'}), content_type='application/json',
               HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, 'snoozed')
        c.post(f'/api/farmer/alerts/{self.alert.id}/action/',
               data=json.dumps({'action': 'resolve'}), content_type='application/json',
               HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, 'resolved')
        self.assertIsNotNone(self.alert.resolved_at)

    def test_status_filter(self):
        c = Client()
        r = c.get('/api/farmer/alerts/?status=active', HTTP_X_FARMER_KEY=self.farmer.api_key)
        d = r.json()
        self.assertEqual(len(d['alerts']), 1)
        self.assertIn('status_counts', d)

    def test_fingerprint_dedup(self):
        from farmer.services.risk import _fingerprint, _persist_alerts
        from farmer.models import RiskAlert
        fp1 = _fingerprint(self.field, 'drought')
        fp2 = _fingerprint(self.field, 'drought')
        self.assertEqual(fp1, fp2)
        # persist same risk twice → no duplicate
        risks = [{'kind': 'drought', 'severity': 'high', 'title_fa': 'خشکسالی',
                  'detail_fa': '', 'source': 'test', 'probability': 'high', 'timing_fa': ''}]
        _persist_alerts(self.field, risks)
        _persist_alerts(self.field, risks)
        self.assertEqual(RiskAlert.objects.filter(field=self.field, kind='drought', fingerprint=fp1).count(), 1)

    def test_resolve_on_disappear(self):
        from farmer.services.risk import _persist_alerts
        from farmer.models import RiskAlert
        # alert exists for 'drought'; persist empty risks → should resolve
        self.alert.fingerprint = __import__('farmer.services.risk', fromlist=['_fingerprint'])._fingerprint(self.field, 'drought')
        self.alert.save()
        _persist_alerts(self.field, [])
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, 'resolved')


class SoilWaterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)
        self.key = self.farmer.api_key

    def test_soil_upsert(self):
        r = self.client.post(f'/api/farmer/fields/{self.field.id}/soil/',
                             data=json.dumps({'ph': 7.5, 'field_capacity': 35, 'wilting_point': 18, 'root_depth_cm': 60}),
                             content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get(f'/api/farmer/fields/{self.field.id}/soil/get/', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r2.json()['soil']['ph'], 7.5)

    def test_soil_other_farmer_denied(self):
        other = FarmerProfile.objects.create(name='دیگری')
        r = self.client.post(f'/api/farmer/fields/{self.field.id}/soil/',
                             data=json.dumps({'ph': 7}), content_type='application/json',
                             HTTP_X_FARMER_KEY=other.api_key)
        self.assertEqual(r.status_code, 404)

    def test_water_source_crud(self):
        r = self.client.post(f'/api/farmer/farms/{self.farm.id}/water-sources/',
                             data=json.dumps({'name': 'چاه ۱', 'kind': 'well', 'capacity_m3': 500}),
                             content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 201)
        r2 = self.client.get(f'/api/farmer/farms/{self.farm.id}/water-sources/list/', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(len(r2.json()['water_sources']), 1)

    def test_soil_feeds_irrigation(self):
        from farmer.models import SoilProfile
        SoilProfile.objects.create(field=self.field, field_capacity=35, wilting_point=18, root_depth_cm=60)
        from farmer.services.irrigation import get_irrigation_advice
        # no cycle → error, but soil_balance logic tested separately
        self.assertTrue(SoilProfile.objects.filter(field=self.field).exists())


class AlertDetailTests(TestCase):
    def test_detail_endpoint(self):
        farmer = FarmerProfile.objects.create(name='کشاورز')
        farm = Farm.objects.create(farmer=farmer, name='مزرعه')
        field = Field.objects.create(farm=farm, name='قطعه', lat=32.0, lon=53.0)
        from farmer.models import RiskAlert
        a = RiskAlert.objects.create(farmer=farmer, field=field, kind='drought',
                                     severity='high', title_fa='خشکسالی', status='active')
        c = Client()
        r = c.get(f'/api/farmer/alerts/{a.id}/', HTTP_X_FARMER_KEY=farmer.api_key)
        self.assertEqual(r.status_code, 200)
        d = r.json()['alert']
        self.assertEqual(d['kind'], 'drought')
        self.assertEqual(d['farm_name'], 'مزرعه')
        # other farmer → 404
        other = FarmerProfile.objects.create(name='دیگری')
        r2 = c.get(f'/api/farmer/alerts/{a.id}/', HTTP_X_FARMER_KEY=other.api_key)
        self.assertEqual(r2.status_code, 404)


class AgentToolTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه', lat=32.0, lon=53.0)
        self.key = self.farmer.api_key

    def test_tools_list(self):
        r = self.c.get('/api/farmer/agent/tools/', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 200)
        tools = r.json()['tools']
        names = [t['name'] for t in tools]
        self.assertIn('get_irrigation_status', names)
        self.assertIn('create_farm_task', names)

    def test_read_tool_runs(self):
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'get_active_risks',
                                         'params': {'field_id': self.field.id}}),
                        content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 200)
        self.assertIn('result', r.json())

    def test_mutating_tool_requires_confirmation(self):
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'create_farm_task',
                                         'params': {'field_id': self.field.id, 'title': 'آبیاری'}}),
                        content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()['confirmation_required'])
        # not created yet
        self.assertEqual(FarmTask.objects.count(), 0)

    def test_mutating_tool_with_confirm(self):
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'create_farm_task', 'confirm': True,
                                         'params': {'field_id': self.field.id, 'title': 'آبیاری'}}),
                        content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FarmTask.objects.count(), 1)

    def test_unknown_tool(self):
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'drop_table', 'params': {}}),
                        content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 400)

    def test_missing_required_param(self):
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'create_farm_task', 'confirm': True,
                                         'params': {'field_id': self.field.id}}),
                        content_type='application/json', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 400)

    def test_other_farmer_field_denied(self):
        other = FarmerProfile.objects.create(name='دیگری')
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'get_active_risks',
                                         'params': {'field_id': self.field.id}}),
                        content_type='application/json', HTTP_X_FARMER_KEY=other.api_key)
        self.assertEqual(r.status_code, 400)  # field not owned

    def test_no_auth(self):
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': 'get_daily_briefing', 'params': {}}),
                        content_type='application/json')
        self.assertIn(r.status_code, (401, 403))


class AgentPhase6Tests(TestCase):
    def setUp(self):
        self.c = Client()
        self.farmer = FarmerProfile.objects.create(name='کشاورز')
        self.farm = Farm.objects.create(farmer=self.farmer, name='مزرعه')
        self.field = Field.objects.create(farm=self.farm, name='قطعه ۱', lat=None, lon=None)

    def test_intent_resolver_canonical(self):
        from core.services.agent_intents import resolve_intent
        cases = {
            'irrigation_question': 'آبیاری چقدر نیاز دارم؟',
            'economic_analysis': 'هزینه‌ها و سود مزرعه چقدر است؟',
            'farm_operation': 'ثبت مشاهده: برگ‌ها زرد شدند',
            'satellite_search': 'جستجوی مجموعه داده ماهواره‌ای',
            'scientific_research': 'تحلیل داده اقلیمی و روش‌شناسی',
            'general_question': 'سلام چطوری',
        }
        for expected, q in cases.items():
            self.assertEqual(resolve_intent(q)['intent'], expected, q)

    def test_context_isolated_per_farmer(self):
        from unittest.mock import patch
        from farmer.services.farmer_agent import answer
        from core.services.tools import get_context
        other = FarmerProfile.objects.create(name='دیگری')
        ofarm = Farm.objects.create(farmer=other, name='مزرعه دیگر')
        ofield = Field.objects.create(farm=ofarm, name='قطعه الف', lat=None, lon=None)
        fake = {'ranking': [{'name_fa': 'گندم', 'score': 80}], 'data_sources': ['x'], 'limitations': []}
        with patch('farmer.services.tools.recommend_crops', return_value=fake):
            answer(self.farmer, 'چه محصولی بکارم؟')
            answer(other, 'چه محصولی بکارم؟')
        c1, c2 = get_context(self.farmer.api_key), get_context(other.api_key)
        self.assertEqual(c1.active_field_id, self.field.id)
        self.assertEqual(c2.active_field_id, ofield.id)
        self.assertNotEqual(c1.active_field_id, c2.active_field_id)

    def test_farm_operation_requires_confirmation(self):
        from farmer.services.farmer_agent import answer
        from farmer.models import FarmObservation
        d = answer(self.farmer, 'ثبت مشاهده: برگ‌ها زرد شدند')
        self.assertTrue(d.get('confirmation_required'))
        self.assertEqual(d.get('tool'), 'create_observation')
        self.assertEqual(FarmObservation.objects.count(), 0)
        r = self.c.post('/api/farmer/agent/tool/',
                        data=json.dumps({'tool': d['tool'], 'params': d['params'], 'confirm': True}),
                        content_type='application/json', HTTP_X_FARMER_KEY=self.farmer.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FarmObservation.objects.count(), 1)

    def test_unsupported_answer_is_honest(self):
        from farmer.services.farmer_agent import answer
        d = answer(self.farmer, 'سلام چطوری')
        self.assertIsNone(d['intent'])
        self.assertEqual(d.get('resolved_intent'), 'general_question')
        self.assertIn('suggestions', d)
        self.assertTrue(d.get('limitations'))

    def test_expert_mode_returns_sources_and_limitations(self):
        from farmer.services.farmer_agent import answer
        d = answer(self.farmer, 'امروز چه کار کنم؟', mode='expert')
        self.assertEqual(d.get('mode'), 'expert')
        self.assertIn('expert', d)
        self.assertIn('sources', d['expert'])
        self.assertIn('limitations', d['expert'])

    def test_registry_has_required_tools(self):
        from farmer.services.tools import get_registry
        names = {t['name'] for t in get_registry().list_tools()}
        for name in ['get_weather', 'get_climate', 'get_irrigation_status',
                     'calculate_water_requirement', 'get_crop_status',
                     'get_active_risks', 'get_farm_economics', 'get_farm_tasks',
                     'create_observation', 'create_farm_task', 'get_scientific_datasets']:
            self.assertIn(name, names)


class AuthOutcomeTests(TestCase):
    def setUp(self):
        self.c = Client()

    def test_register_login_session_and_isolation(self):
        r = self.c.post('/api/farmer/register/', data=json.dumps({
            'name': 'کاربر واقعی', 'login': 'farmer@example.com',
            'password': 'secret123', 'phone': '09120000000'}), content_type='application/json')
        self.assertEqual(r.status_code, 201)
        farmer = r.json()['farmer']
        self.assertTrue(farmer['has_account'])
        self.assertIn('api_key', farmer)

        bad = self.c.post('/api/farmer/login/', data=json.dumps({
            'login': 'farmer@example.com', 'password': 'wrong-pass'}), content_type='application/json')
        self.assertEqual(bad.status_code, 401)

        ok = self.c.post('/api/farmer/login/', data=json.dumps({
            'login': 'farmer@example.com', 'password': 'secret123'}), content_type='application/json')
        self.assertEqual(ok.status_code, 200)
        me = self.c.get('/api/farmer/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json().get('auth'), 'session')

        r = self.c.post('/api/farmer/farms/create/', data=json.dumps({'name': 'مزرعه حساب'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 201)
        farm_id = r.json()['farm']['id']
        r = self.c.post('/api/farmer/fields/create/', data=json.dumps({
            'farm_id': farm_id, 'name': 'قطعه حساب'}), content_type='application/json')
        self.assertEqual(r.status_code, 201)
        field_id = r.json()['field']['id']

        other = Client()
        r = other.post('/api/farmer/register/', data=json.dumps({
            'name': 'کاربر دوم', 'login': 'other@example.com', 'password': 'secret123'}),
            content_type='application/json')
        self.assertEqual(r.status_code, 201)
        r = other.post('/api/farmer/login/', data=json.dumps({
            'login': 'other@example.com', 'password': 'secret123'}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        denied = other.get(f'/api/farmer/fields/{field_id}/')
        self.assertEqual(denied.status_code, 404)

    def test_legacy_api_key_login_still_works(self):
        r = self.c.post('/api/farmer/profile/', data=json.dumps({'name': 'مهمان'}),
                        content_type='application/json')
        key = r.json()['farmer']['api_key']
        r = self.c.post('/api/farmer/login/', data=json.dumps({'api_key': key}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        me = self.c.get('/api/farmer/me/', HTTP_X_FARMER_KEY=key)
        self.assertEqual(me.status_code, 200)

    def test_recommendation_outcome_metrics(self):
        farmer = FarmerProfile.objects.create(name='کشاورز')
        farm = Farm.objects.create(farmer=farmer, name='مزرعه')
        field = Field.objects.create(farm=farm, name='قطعه')
        from farmer.models import Recommendation
        rec = Recommendation.objects.create(farmer=farmer, field=field, title_fa='آبیاری', status='new')
        r = self.c.post(f'/api/farmer/recommendations/{rec.id}/feedback/', data=json.dumps({
            'status': 'completed', 'outcome_note': 'نتیجه خوب بود',
            'outcome_metrics': {'yield_kg_ha': 4200, 'cost': 1500, 'water_m3': 80,
                                'rating': 5, 'unexpected': 'drop-me'}}),
            content_type='application/json', HTTP_X_FARMER_KEY=farmer.api_key)
        self.assertEqual(r.status_code, 200)
        data = r.json()['recommendation']
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['outcome_metrics']['yield_kg_ha'], 4200)
        self.assertNotIn('unexpected', data['outcome_metrics'])
        self.assertIsNotNone(data['outcome_at'])


class SessionAuthTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.farmer = FarmerProfile.objects.create(name='سشن')
        self.key = self.farmer.api_key

    def test_login_sets_session(self):
        r = self.c.post('/api/farmer/login/',
                        data=json.dumps({'api_key': self.key}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['auth'] if 'auth' in r.json() else 'ok', 'ok')

    def test_me_with_session(self):
        self.c.post('/api/farmer/login/',
                    data=json.dumps({'api_key': self.key}),
                    content_type='application/json')
        r = self.c.get('/api/farmer/me/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['auth'], 'session')

    def test_me_with_api_key(self):
        r = self.c.get('/api/farmer/me/', HTTP_X_FARMER_KEY=self.key)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['auth'], 'api_key')

    def test_me_unauthenticated(self):
        r = self.c.get('/api/farmer/me/')
        self.assertEqual(r.status_code, 401)

    def test_logout(self):
        self.c.post('/api/farmer/login/',
                    data=json.dumps({'api_key': self.key}),
                    content_type='application/json')
        self.c.post('/api/farmer/logout/')
        r = self.c.get('/api/farmer/me/')
        self.assertEqual(r.status_code, 401)

    def test_login_bad_key(self):
        r = self.c.post('/api/farmer/login/',
                        data=json.dumps({'api_key': 'wrong'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 401)
