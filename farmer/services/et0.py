"""FAO-56 Penman-Monteith ET0 engine (Phase 3).

Computes reference evapotranspiration from NASA POWER daily parameters:
  T2M (°C), RH2M (%), WS10M (m/s), ALLSKY_SFC_SW_DWN (kWh/m²/day),
  PS (kPa), PRECTOTCORR (mm/day).

All formulas follow FAO-56 (Allen et al., 1998). Approximations are
documented; when required inputs are missing the function returns
method='unavailable' instead of inventing a number.

Golden-testable: pure functions, no I/O.
"""
import math
from datetime import date, timedelta

# FAO-56 constants
G_SC = 0.0820          # solar constant, MJ m-2 min-1
SIGMA = 4.903e-9       # Stefan-Boltzmann, MJ K-4 m-2 day-1
LAMBDA = 2.45          # latent heat of vaporization, MJ/kg


def _sat_vp(t):
    """Saturation vapour pressure (kPa) at air temperature T (°C)."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def _delta_slope(t):
    """Slope of saturation vapour pressure curve (kPa/°C)."""
    return 4098 * _sat_vp(t) / ((t + 237.3) ** 2)


def _wind_u2(ws10):
    """Convert 10m wind speed to 2m (FAO-56 eq. 47)."""
    return ws10 * 4.87 / math.log(67.8 * 10 - 5.42)


def _extraterrestrial_radiation(lat_deg, doy):
    """Ra (MJ/m²/day) — FAO-56 eq. 21."""
    lat = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(-math.tan(lat) * math.tan(delta))
    return (24 * 60 / math.pi) * G_SC * dr * (
        ws * math.sin(lat) * math.sin(delta) +
        math.cos(lat) * math.cos(delta) * math.sin(ws))


def _net_radiation(rs_mj, tmin, tmax, rh_min, rh_max, lat_deg, doy):
    """Net radiation Rn (MJ/m²/day) — FAO-56 eq. 38-40 (simplified).

    Rs from ALLSKY_SFC_SW_DWN (kWh/m²/day → MJ/m²/day ×3.6).
    Rso estimated via Hargreaves clear-sky formula.
    """
    rs = rs_mj * 3.6  # kWh → MJ
    ra = _extraterrestrial_radiation(lat_deg, doy)
    # clear-sky radiation (FAO-56 eq. 37, Angström with default coefficients)
    rso = (0.75 + 2e-5 * 0) * ra  # simplified: 0.75*Ra
    # net shortwave
    alpha = 0.23
    rns = (1 - alpha) * rs
    # net longwave (FAO-56 eq. 39)
    tmean = (tmin + tmax) / 2
    es_tmax = _sat_vp(tmax)
    es_tmin = _sat_vp(tmin)
    es_mean = (es_tmax + es_tmin) / 2
    ea = es_mean * (rh_min / 100 + rh_max / 100) / 2
    cloud = min(rs / rso, 1.0) if rso > 0 else 0.5
    rnl = SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * \
        (0.34 - 0.14 * math.sqrt(max(ea, 0.01))) * \
        (1.35 * cloud - 0.35)
    return rns - rnl


def et0_penman_monteith(t2m, rh2m, ws10, rs_kwh, ps_kpa, lat_deg, doy,
                        tmin=None, tmax=None):
    """FAO-56 PM ET0 (mm/day) from daily POWER parameters.

    Returns dict with et0_mm, method, inputs_used, limitations.
    If critical inputs missing → method='unavailable'.
    """
    missing = []
    for name, v in [('T2M', t2m), ('RH2M', rh2m), ('WS10M', ws10),
                    ('ALLSKY_SFC_SW_DWN', rs_kwh), ('PS', ps_kpa)]:
        if v is None:
            missing.append(name)
    if missing:
        return {'et0_mm': None, 'method': 'unavailable',
                'inputs_used': [], 'limitations': [f'Missing inputs: {missing}'],
                'missing': missing}

    tmin = tmin if tmin is not None else t2m - 5   # documented fallback
    tmax = tmax if tmax is not None else t2m + 5
    u2 = _wind_u2(ws10)
    es = (_sat_vp(tmax) + _sat_vp(tmin)) / 2
    ea = es * rh2m / 100
    delta = _delta_slope(t2m)
    gamma = 0.000665 * ps_kpa
    rn = _net_radiation(rs_kwh, tmin, tmax, rh2m, rh2m, lat_deg, doy)
    g = 0.0  # daily: soil heat flux ≈ 0 (FAO-56)

    num = 0.408 * delta * (rn - g) + gamma * (900 / (t2m + 273)) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    et0 = num / den if den != 0 else None

    limitations = []
    if tmin is None or tmax is None:
        limitations.append('Tmin/Tmax not provided — estimated as T2M±5°C')
    limitations.append('Rso approximated as 0.75·Ra (no elevation correction)')
    limitations.append('u2 converted from 10m wind (FAO-56 eq.47)')

    return {'et0_mm': round(et0, 2) if et0 is not None else None,
            'method': 'FAO56_PM',
            'inputs_used': ['T2M', 'RH2M', 'WS10M', 'ALLSKY_SFC_SW_DWN', 'PS'],
            'limitations': limitations,
            'intermediate': {'u2': round(u2, 2), 'es': round(es, 3),
                             'ea': round(ea, 3), 'delta': round(delta, 4),
                             'gamma': round(gamma, 5), 'rn': round(rn, 2)}}


def et0_hargreaves(tmin, tmax, lat_deg, doy, rs_kwh=None):
    """FAO-56 Hargreaves ET0 (mm/day) — fallback when PM inputs missing.

    ET0 = 0.0023 × (Tmean+17.8) × √(Tmax−Tmin) × Ra
    """
    if tmin is None or tmax is None:
        return {'et0_mm': None, 'method': 'unavailable',
                'limitations': ['Tmin/Tmax required for Hargreaves']}
    tmean = (tmin + tmax) / 2
    ra = _extraterrestrial_radiation(lat_deg, doy)  # MJ/m²/day
    et0 = 0.0023 * (tmean + 17.8) * math.sqrt(max(tmax - tmin, 0)) * ra
    return {'et0_mm': round(et0, 2), 'method': 'FAO56_HARGREAVES',
            'limitations': ['Temperature-only method — less accurate than PM',
                            'Requires Tmax/Tmin which POWER daily provides']}


def get_et0_daily(field, days=30):
    """Fetch POWER daily params and compute ET0 series.

    Returns {'series': [...], 'method': ..., 'limitations': [...]}.
    """
    from core.services.nasa import fetch_power
    end = date.today()
    start = end - timedelta(days=days)
    params = ['T2M', 'T2M_MAX', 'T2M_MIN', 'RH2M', 'WS10M',
              'ALLSKY_SFC_SW_DWN', 'PS', 'PRECTOTCORR']
    try:
        data = fetch_power(field.lat, field.lon,
                           start.strftime('%Y%m%d'), end.strftime('%Y%m%d'),
                           parameters=params, temporal='daily')
    except Exception as e:
        return {'series': [], 'method': 'unavailable',
                'limitations': [f'POWER fetch failed: {e}'], 'error': str(e)}

    # index params by date
    by_date = {}
    for p in data.get('parameters', []):
        for pt in p.get('points', []):
            by_date.setdefault(pt['date'], {})[p['code']] = pt['value']

    series = []
    methods = set()
    for d_str, vals in sorted(by_date.items()):
        try:
            doy = date(int(d_str[:4]), int(d_str[4:6]), int(d_str[6:8])).timetuple().tm_yday
        except Exception:
            continue
        r = et0_penman_monteith(
            vals.get('T2M'), vals.get('RH2M'), vals.get('WS10M'),
            vals.get('ALLSKY_SFC_SW_DWN'), vals.get('PS'),
            field.lat, doy, tmin=vals.get('T2M_MIN'), tmax=vals.get('T2M_MAX'))
        if r['et0_mm'] is None:
            r = et0_hargreaves(vals.get('T2M_MIN'), vals.get('T2M_MAX'),
                               field.lat, doy)
        methods.add(r['method'])
        series.append({'date': d_str, 'et0_mm': r['et0_mm'],
                       'method': r['method'], 'precip_mm': vals.get('PRECTOTCORR'),
                       'limitations': r.get('limitations', [])})

    return {'series': series,
            'method': '+'.join(methods) if methods else 'unavailable',
            'days': len(series),
            'limitations': ['ET0 is reference evapotranspiration — actual crop water use = Kc × ET0'],
            'data_date': date.today().isoformat()}
