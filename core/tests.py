import json
from django.conf import settings
from django.test import SimpleTestCase, TestCase, Client

class ObservatoryAPITests(TestCase):
    def setUp(self):
        from farmer.models import FarmerProfile
        f = FarmerProfile.objects.create(name='observer')
        s = self.client.session
        s['farmer_id'] = f.id
        s.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key

    def test_health(self):
        response=self.client.get('/api/health/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'ok')

    def test_power_rejects_invalid_coordinates_without_external_call(self):
        response=self.client.get('/api/power/',{'lat':'91','lon':'0','start':'20250101','end':'20250102'})
        self.assertEqual(response.status_code,400)
        self.assertIn('Latitude',response.json()['error'])

    def test_power_rejects_bad_date(self):
        response=self.client.get('/api/power/',{'lat':'30','lon':'50','start':'01-01-2025','end':'20250102'})
        self.assertEqual(response.status_code,400)

    def test_invalid_granule_collection_id(self):
        response=self.client.get('/api/granules/',{'concept_id':'not-a-cmr-id'})
        self.assertEqual(response.status_code,400)

    def test_faq_is_bilingual_and_searchable(self):
        fa=self.client.get('/api/faq/',{'lang':'fa','q':'رطوبت خاک'})
        en=self.client.get('/api/faq/',{'lang':'en','q':'soil moisture'})
        self.assertEqual(fa.status_code,200)
        self.assertGreater(fa.json()['count'],0)
        self.assertGreater(en.json()['count'],0)

    def test_dashboard_renders(self):
        response=self.client.get('/observatory/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'NASA EARTH OBSERVATORY')


class FaoApiTests(TestCase):
    def setUp(self):
        from farmer.models import FarmerProfile
        f = FarmerProfile.objects.create(name='fao-user')
        s = self.client.session
        s['farmer_id'] = f.id
        s.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key

    def test_fao_crop_list(self):
        response=self.client.get('/api/fao/crops/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['source'],'FAOSTAT')
        self.assertIn('wheat',[x['key'] for x in response.json()['items']])

    def test_fao_unknown_crop_is_rejected(self):
        response=self.client.get('/api/fao/crops/not-a-crop/')
        self.assertEqual(response.status_code,400)

    def test_fao_data_is_never_fabricated_on_upstream_failure(self):
        from unittest.mock import patch
        from core.services.http import DataSourceError
        with patch('core.services.fao.fetch_json', side_effect=DataSourceError('offline', source='FAOSTAT')):
            response=self.client.get('/api/fao/crops/wheat/?refresh=1')
        self.assertEqual(response.status_code,502)
        self.assertIn('داده نمونه جایگزین نشده',response.json()['error'])


class HttpLayerTests(SimpleTestCase):
    def test_rejects_non_https(self):
        from core.services.http import validate_url, DataSourceError
        with self.assertRaises(DataSourceError):
            validate_url('http://power.larc.nasa.gov/x')

    def test_rejects_unknown_host(self):
        from core.services.http import validate_url, DataSourceError
        with self.assertRaises(DataSourceError):
            validate_url('https://evil.example.com/x')

    def test_rejects_credentials_in_url(self):
        from core.services.http import validate_url, DataSourceError
        with self.assertRaises(DataSourceError):
            validate_url('https://user:pass@power.larc.nasa.gov/x')

    def test_accepts_whitelisted_host(self):
        from core.services.http import validate_url
        self.assertIn('power.larc.nasa.gov', validate_url('https://power.larc.nasa.gov/api/x'))

    def test_fetch_json_retries_on_500(self):
        from unittest.mock import patch, Mock
        from core.services.http import fetch_json, DataSourceError
        ok = Mock(status_code=200, iter_content=lambda n: [b'{"a":1}'], headers={})
        bad = Mock(status_code=500)
        with patch('core.services.http.requests.request', side_effect=[bad, ok]), \
             patch('core.services.http.time.sleep'):
            self.assertEqual(fetch_json('https://power.larc.nasa.gov/api/x', max_retries=1), {'a': 1})

    def test_fetch_json_raises_after_retries(self):
        from unittest.mock import patch, Mock
        from core.services.http import fetch_json, DataSourceError
        with patch('core.services.http.requests.request', return_value=Mock(status_code=503)), \
             patch('core.services.http.time.sleep'):
            with self.assertRaises(DataSourceError):
                fetch_json('https://power.larc.nasa.gov/api/x', max_retries=1)


class RateLimitTests(SimpleTestCase):
    def test_rate_limit_returns_429_after_threshold(self):
        from django.core.cache import cache
        from core.services.throttle import rate_limit
        from django.http import JsonResponse
        cache.clear()
        @rate_limit(2, 60, 'test-scope')
        def view(request):
            return JsonResponse({'ok': True})
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get('/api/health/')
        self.assertEqual(view(req).status_code, 200)
        self.assertEqual(view(req).status_code, 200)
        resp = view(req)
        self.assertEqual(resp.status_code, 429)
        self.assertTrue(resp['Retry-After'].isdigit())
        self.assertLessEqual(int(resp['Retry-After']), 60)


class ClimateMathTests(SimpleTestCase):
    def test_norm_ppf_known_values(self):
        from core.services.climate import _norm_ppf
        self.assertAlmostEqual(_norm_ppf(0.5), 0.0, places=3)
        self.assertAlmostEqual(_norm_ppf(0.975), 1.96, places=2)
        self.assertAlmostEqual(_norm_ppf(0.025), -1.96, places=2)

    def test_gamma_p_bounds(self):
        from core.services.climate import _gamma_p
        self.assertEqual(_gamma_p(2, 0), 0.0)
        self.assertAlmostEqual(_gamma_p(1, 1), 1 - 2.718281828 ** -1, places=3)
        self.assertTrue(0 <= _gamma_p(3, 5) <= 1)

    def test_spi_insufficient_data_returns_none(self):
        from core.services.climate import _spi_series
        self.assertIsNone(_spi_series([10.0] * 8, 12))

    def test_spi_constant_series_is_zero(self):
        from core.services.climate import _spi_series
        out = _spi_series([20.0] * 20, 3)
        self.assertTrue(all(v == 0.0 for v in out))

    def test_hargreaves_pet_positive(self):
        from core.services.climate import _hargreaves_pet
        pet = _hargreaves_pet(35, 20, 32.0, 200)
        self.assertGreater(pet, 0)
        self.assertLess(pet, 20)


class AgentIntentTests(SimpleTestCase):
    def test_detect_drought(self):
        from core.services.agent import _detect_intent
        intent, conf = _detect_intent('وضعیت خشکسالی در شیراز چطور است؟')
        self.assertEqual(intent, 'drought')
        self.assertGreater(conf, 0)

    def test_detect_crop_advice(self):
        from core.services.agent import _detect_intent, _detect_crop
        intent, _ = _detect_intent('توصیه آبیاری برای گندم در مشهد')
        self.assertEqual(intent, 'crop_advice')
        self.assertEqual(_detect_crop('وضعیت گندم در شیراز'), 'wheat')

    def test_detect_production(self):
        from core.services.agent import _detect_intent
        intent, _ = _detect_intent('تولید جهانی گندم چقدر است؟')
        self.assertEqual(intent, 'production')

    def test_unknown_question(self):
        from core.services.agent import _detect_intent
        intent, conf = _detect_intent('سلام چطوری')
        self.assertIsNone(intent)

    def test_agent_never_guesses_location(self):
        from unittest.mock import patch
        from core.services import agent
        with patch('core.services.agent.search_places', return_value=[]):
            d = agent.answer_question('وضعیت خشکسالی چطور است؟')
        self.assertIn('موقعیت', d.get('answer_fa', ''))


class ReportTests(SimpleTestCase):
    def test_pdf_builds_from_climate_data(self):
        from core.services.report import build_climate_pdf
        data = {'source': 'NASA POWER', 'fetched_at': '2026-11-12T00:00:00+00:00',
                'location': {'lat': 32.0, 'lon': 34.0},
                'period': {'start': '2021-11-01', 'end': '2026-11-01', 'months': 61},
                'indicators': {'spi_6m': {'value': -1.2, 'unit': 'dimensionless',
                                          'formula': 'SPI-6 gamma', 'source': 'NASA POWER'}},
                'monthly': [{'month': '2026-10', 'tmean_c': 20.0, 'tmax_c': 30.0,
                             'tmin_c': 10.0, 'precip_mm': 5.0, 'pet_mm': 40.0,
                             'water_balance_mm': -35.0}],
                'limitations': ['test limitation']}
        pdf = build_climate_pdf(data)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 1000)


class FaoWorldTests(SimpleTestCase):
    def _payload(self):
        return {'data': [
            {'Element Code': '2510', 'Year': '2022', 'Value': '100', 'Unit': 't',
             'Area Code': '351', 'Area': 'China'},
            {'Element Code': '2510', 'Year': '2021', 'Value': '90', 'Unit': 't',
             'Area Code': '351', 'Area': 'China'},
            {'Element Code': '2510', 'Year': '2022', 'Value': '50', 'Unit': 't',
             'Area Code': '102', 'Area': 'Iran'},
            {'Element Code': '2510', 'Year': '2022', 'Value': '30', 'Unit': 't',
             'Area Code': '231', 'Area': 'United States'},
        ]}

    def test_world_ranking_and_iran_position(self):
        from unittest.mock import patch
        from core.services import fao
        from django.core.cache import cache
        cache.clear()
        with patch('core.services.fao._request_faostat', return_value=(self._payload(), 'https://x')):
            d = fao.fetch_world('wheat', element='production', top=5)
        self.assertEqual(d['ranking'][0]['area_code'], '351')
        self.assertEqual(d['iran']['rank'], 2)
        self.assertEqual(d['iran']['value'], 50)
        self.assertIn('102', d['comparison'])
        self.assertEqual(len(d['comparison']['102']['points']), 1)

    def test_world_rejects_bad_element(self):
        from core.services import fao
        with self.assertRaises(ValueError):
            fao.fetch_world('wheat', element='bogus')


class FaoParsingTests(SimpleTestCase):
    def test_yield_hg_per_hectare_is_normalized_to_tonnes_per_hectare(self):
        from core.services.fao import _parse
        parsed=_parse({'data':[{'Element Code':'2413','Year':'2020','Value':'45000','Unit':'hg/ha'}]})
        self.assertEqual(parsed['yield'][0]['value'],4.5)
        self.assertEqual(parsed['yield'][0]['unit'],'tonnes/ha')


class DataContractTests(SimpleTestCase):
    def _c(self, **kw):
        from core.services.data_contract import DataContract
        base = dict(source='NASA POWER', dataset_id='power_daily_point',
                    kind='numeric', parameter='T2M', value=25.0,
                    original_unit='°C', lat=32.0, lon=53.0,
                    temporal_resolution='daily', retrieved_at='2026-11-13T10:00:00+00:00')
        base.update(kw)
        return DataContract(**base)

    def test_valid_contract(self):
        from core.services.data_contract import validate_contract, quality_from_issues
        issues = validate_contract(self._c())
        self.assertEqual(issues, [])
        self.assertEqual(quality_from_issues(issues), 'valid')

    def test_missing_source(self):
        from core.services.data_contract import validate_contract, quality_from_issues
        c = self._c(source='')
        issues = validate_contract(c)
        self.assertIn('missing_source', issues)
        self.assertEqual(quality_from_issues(issues), 'invalid')

    def test_bad_coordinates(self):
        from core.services.data_contract import validate_contract
        issues = validate_contract(self._c(lat=95))
        self.assertIn('lat_out_of_range', issues)

    def test_unit_mismatch(self):
        from core.services.data_contract import validate_contract
        issues = validate_contract(self._c(original_unit='°F'), expected_unit='°C')
        self.assertIn('unit_mismatch', issues)

    def test_stale_data(self):
        from core.services.data_contract import validate_contract, quality_from_issues
        c = self._c(retrieved_at='2020-01-01T00:00:00+00:00')
        issues = validate_contract(c, max_age_days=30)
        self.assertIn('stale_data', issues)
        self.assertEqual(quality_from_issues(issues), 'stale')

    def test_value_out_of_range(self):
        from core.services.data_contract import validate_contract
        issues = validate_contract(self._c(value=200.0))
        self.assertIn('value_out_of_range', issues)

    def test_imagery_kind_no_value(self):
        from core.services.data_contract import validate_contract
        c = self._c(kind='imagery', value=None, parameter='')
        issues = validate_contract(c)
        self.assertEqual(issues, [])


class ProvenanceTests(SimpleTestCase):
    def test_power_provenance_shape(self):
        from core.services.nasa import _power_provenance
        p = _power_provenance(32.0, 53.0, 'daily', 'AG', 'https://example.com')
        self.assertEqual(p['source'], 'NASA POWER')
        self.assertEqual(p['dataset_id'], 'power_daily_point')
        self.assertIn('retrieved_at', p)
        self.assertIn('quality_status', p)
        self.assertEqual(p['lat'], 32.0)

    def test_fao_provenance_shape(self):
        from core.services.fao import _fao_provenance
        p = _fao_provenance('wheat', 'yield')
        self.assertEqual(p['source'], 'FAOSTAT')
        self.assertEqual(p['kind'], 'statistics')
        self.assertIn('quality_status', p)


class DataModelTests(SimpleTestCase):
    def test_models_exist(self):
        from core.models import DataSource, Dataset, DataSnapshot, DataIngestionLog
        self.assertTrue(all([DataSource, Dataset, DataSnapshot, DataIngestionLog]))


class ProvenanceStoreTests(TestCase):
    def test_log_fetch_creates_source_and_log(self):
        from core.services.provenance_store import log_fetch
        from core.models import DataSource, DataIngestionLog
        log_fetch('nasa_power', 'power_daily_point', 'https://x', status='success', duration_ms=120)
        self.assertTrue(DataSource.objects.filter(key='nasa_power').exists())
        self.assertEqual(DataIngestionLog.objects.filter(status='success').count(), 1)

    def test_log_fetch_error(self):
        from core.services.provenance_store import log_fetch
        from core.models import DataIngestionLog
        log_fetch('faostat', '', 'https://y', status='error', error_message='timeout')
        log = DataIngestionLog.objects.latest('id')
        self.assertEqual(log.status, 'error')
        self.assertIn('timeout', log.error_message)

    def test_record_snapshot(self):
        from core.services.provenance_store import record_snapshot
        from core.models import DataSnapshot, Dataset
        contract = {'source': 'NASA POWER', 'dataset_id': 'power_daily_point',
                    'kind': 'numeric', 'parameter': 'T2M', 'lat': 32.0, 'lon': 53.0,
                    'quality_status': 'valid', 'limitations': ['grid estimate'],
                    'retrieved_at': '2026-11-13T10:00:00+00:00'}
        sid = record_snapshot('nasa_power', 'power_daily_point', '32,53,20250101-20250131',
                              contract, payload_ref='https://power.larc.nasa.gov/x')
        self.assertIsNotNone(sid)
        snap = DataSnapshot.objects.get(id=sid)
        self.assertEqual(snap.quality_status, 'valid')
        self.assertEqual(snap.dataset.key, 'power_daily_point')
        self.assertEqual(snap.metadata['lat'], 32.0)

    def test_record_snapshot_never_raises(self):
        from core.services.provenance_store import record_snapshot
        # bad contract dict should not raise
        sid = record_snapshot('x', 'y', 'z', {})
        self.assertTrue(sid is None or isinstance(sid, int))


class DataQualityEndpointTests(TestCase):
    def setUp(self):
        from farmer.models import FarmerProfile
        f = FarmerProfile.objects.create(name='dq-user')
        s = self.client.session
        s['farmer_id'] = f.id
        s.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key

    def test_data_quality_empty(self):
        r = self.client.get('/api/data-quality/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn('snapshots', d)
        self.assertIn('ingestion_last_24h', d)
        self.assertIn('generated_at', d)

    def test_data_quality_with_snapshot(self):
        from core.services.provenance_store import record_snapshot
        contract = {'source': 'NASA POWER', 'dataset_id': 'power_daily_point',
                    'quality_status': 'valid', 'limitations': []}
        record_snapshot('nasa_power', 'power_daily_point', 'test-key', contract)
        r = self.client.get('/api/data-quality/')
        d = r.json()
        self.assertTrue(any(s['dataset__key'] == 'power_daily_point' for s in d['snapshots']))


class ProviderMockTests(TestCase):
    """Mock-based provider tests - no real external calls."""

    def test_power_success_mock(self):
        from unittest.mock import patch
        from core.services.nasa import fetch_power
        payload = {'geometry': {}, 'header': {},
                   'properties': {'parameter': {'T2M': {'20250101': 20.0, '20250102': 22.0}}}}
        with patch('core.services.nasa.fetch_json', return_value=payload):
            r = fetch_power(32.0, 53.0, '20250101', '20250102', parameters=['T2M'])
        self.assertEqual(r['source'], 'NASA POWER')
        self.assertIn('provenance', r)
        self.assertEqual(r['provenance']['quality_status'], 'valid')

    def test_power_api_failure_mock(self):
        from unittest.mock import patch
        from core.services.nasa import fetch_power
        from core.services.http import DataSourceError
        with patch('core.services.nasa.fetch_json', side_effect=DataSourceError('timeout', source='NASA POWER')):
            with self.assertRaises(ValueError):
                fetch_power(32.0, 53.0, '20250101', '20250102')

    def test_power_empty_data_mock(self):
        from unittest.mock import patch
        from core.services.nasa import fetch_power
        with patch('core.services.nasa.fetch_json', return_value={'properties': {'parameter': {}}}):
            with self.assertRaises(ValueError):
                fetch_power(32.0, 53.0, '20250101', '20250102')

    def test_power_invalid_coords(self):
        from core.services.nasa import fetch_power
        with self.assertRaises(ValueError):
            fetch_power(95.0, 53.0, '20250101', '20250102')

    def test_duplicate_snapshot_reuse(self):
        from core.services.provenance_store import record_snapshot
        from core.models import DataSnapshot
        contract = {'source': 'X', 'dataset_id': 'd', 'quality_status': 'valid'}
        s1 = record_snapshot('nasa_power', 'dup_test', 'same-key', contract)
        s2 = record_snapshot('nasa_power', 'dup_test', 'same-key', contract)
        self.assertEqual(s1, s2)
        self.assertEqual(DataSnapshot.objects.filter(dataset__key='dup_test').count(), 1)

    def test_stale_cache_logged(self):
        from django.core.cache import cache
        from core.services.http import fetch_json
        from unittest.mock import patch
        cache.set('ck1', {'a': 1}, timeout=100)
        cache.set('ck1:ts', 0, timeout=100)
        with patch('core.services.http._request') as m:
            fetch_json('https://power.larc.nasa.gov/x', cache_key='ck1', cache_ttl=100, source='NASA POWER')
        m.assert_not_called()
        from core.models import DataIngestionLog
        self.assertTrue(DataIngestionLog.objects.filter(status='stale').exists())


class SavedAnalysisTests(TestCase):
    def setUp(self):
        from farmer.models import FarmerProfile
        self.farmer = FarmerProfile.objects.create(name='analyst')
        s = self.client.session
        s['farmer_id'] = self.farmer.id
        s.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = s.session_key
        self.c = self.client

    def test_save_list_detail_delete(self):
        r = self.client.post('/api/analyses/save/', data=json.dumps({
            'title': 'POWER Tehran', 'analysis_type': 'power',
            'geo': {'lat': 35.7, 'lon': 51.4}, 'time_range': {'start': '20250101', 'end': '20250110'},
            'data_source': 'NASA POWER', 'parameters': {'lat': 35.7, 'lon': 51.4,
            'start': '20250101', 'end': '20250110', 'parameters': ['T2M']},
            'viz_settings': {'layer': 't2m'}, 'dataset_version': 'POWER v2'}),
            content_type='application/json', HTTP_X_OWNER='tester')
        self.assertEqual(r.status_code, 201)
        aid = r.json()['analysis']['id']
        r2 = self.client.get('/api/analyses/?owner=tester')
        self.assertEqual(r2.json()['count'], 1)
        r3 = self.client.get(f'/api/analyses/{aid}/?owner=tester')
        self.assertEqual(r3.json()['analysis']['title'], 'POWER Tehran')
        # other authenticated account can't see
        from farmer.models import FarmerProfile
        other_farmer = FarmerProfile.objects.create(name='other-analyst')
        oc = Client()
        s = oc.session
        s['farmer_id'] = other_farmer.id
        s.save()
        oc.cookies[settings.SESSION_COOKIE_NAME] = s.session_key
        r4 = oc.get(f'/api/analyses/{aid}/')
        self.assertEqual(r4.status_code, 404)
        r5 = self.client.post(f'/api/analyses/{aid}/delete/', data='{}',
                         content_type='application/json', HTTP_X_OWNER='tester')
        self.assertEqual(r5.status_code, 200)

    def test_export_csv(self):
        r = self.client.post('/api/analyses/save/', data=json.dumps({
            'title': 'X', 'analysis_type': 'power', 'parameters': {'lat': 1}}),
            content_type='application/json', HTTP_X_OWNER='tester')
        aid = r.json()['analysis']['id']
        r2 = self.client.get(f'/api/analyses/{aid}/export/?format=csv&owner=tester')
        self.assertEqual(r2.status_code, 200)
        self.assertIn('text/csv', r2['Content-Type'])
        self.assertIn(b'Data Source', r2.content)

    def test_export_pdf(self):
        r = self.client.post('/api/analyses/save/', data=json.dumps({
            'title': 'X', 'analysis_type': 'power'}),
            content_type='application/json', HTTP_X_OWNER='tester')
        aid = r.json()['analysis']['id']
        r2 = self.client.get(f'/api/analyses/{aid}/export/?format=pdf&owner=tester')
        self.assertEqual(r2.status_code, 200)
        self.assertIn('application/pdf', r2['Content-Type'])
        self.assertTrue(r2.content.startswith(b'%PDF'))

    def test_timeseries_validation(self):
        r = self.client.get('/api/timeseries/')
        self.assertEqual(r.status_code, 400)  # missing params

    def test_reproduce_missing(self):
        r = self.client.get('/api/analyses/999/reproduce/?owner=tester')
        self.assertEqual(r.status_code, 404)
