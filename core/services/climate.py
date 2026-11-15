"""Climate Intelligence Engine — scientific indicators from real NASA POWER data.

Indices implemented (all traceable, no synthetic values):
  - Temperature / precipitation anomaly vs the fetched reference period
  - SPI  (Standardized Precipitation Index, gamma distribution, scales 1/3/6/12)
  - SPEI (Standardized Precipitation-Evapotranspiration Index, log-logistic,
          scales 1/3/6/12; PET via Hargreaves FAO-56 equation 50)
  - Heatwave events (>=3 consecutive days Tmax >= 35 C)
  - Frost days (Tmin <= 0 C), max consecutive dry days, GDD(base 10 C)
  - Monthly water balance (P - PET)

Every indicator carries formula, unit, source, reference period and
limitations metadata per the platform data-display standard.
"""
import math
from collections import defaultdict
from datetime import date, timedelta

from .nasa import fetch_power

POWER_PARAMS = ['T2M', 'T2M_MAX', 'T2M_MIN', 'PRECTOTCORR']
MAX_DAYS = 5 * 366  # ~5 years of daily data


# ---------- statistical helpers ----------

def _norm_ppf(p):
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if p <= 0 or p >= 1:
        return None
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _gamma_p(a, x):
    """Regularized lower incomplete gamma P(a,x) — series / continued fraction."""
    if x <= 0:
        return 0.0
    if x < a + 1:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(300):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-12:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # Q(a,x) via continued fraction, then P = 1 - Q
    b, c, d, h = x + 1 - a, 1e30, 1.0 / (x + 1 - a), 1.0 / (x + 1 - a)
    for i in range(1, 300):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return max(0.0, min(1.0, 1.0 - q))


def _spi_series(values, scale):
    """SPI for one scale: gamma fit (method of moments) + inverse normal."""
    n = len(values)
    if n < scale + 5:
        return None
    sums = [sum(values[i:i + scale]) for i in range(n - scale + 1)]
    mean = sum(sums) / len(sums)
    var = sum((x - mean) ** 2 for x in sums) / max(1, len(sums) - 1)
    if var <= 0:
        return [0.0] * len(sums)
    alpha = mean * mean / var
    beta = var / mean
    out = []
    for x in sums:
        if x <= 0:
            # probability of zero precipitation handled via mixed distribution
            p_zero = sum(1 for s in sums if s == 0) / len(sums)
            f = p_zero + (1 - p_zero) * _gamma_p(alpha, x / beta) if x == 0 else _gamma_p(alpha, x / beta)
        else:
            f = _gamma_p(alpha, x / beta)
        f = min(max(f, 1e-6), 1 - 1e-6)
        out.append(round(_norm_ppf(f), 2))
    return out


def _spei_series(wb, scale):
    """SPEI approximation: log-logistic fit on shifted water balance.

    Water balance D = P - PET can be negative; we shift by (min - eps) so the
    log-logistic CDF is defined, then map through the inverse normal CDF.
    Documented as an approximation in the indicator metadata.
    """
    n = len(wb)
    if n < scale + 5:
        return None
    sums = [sum(wb[i:i + scale]) for i in range(n - scale + 1)]
    shift = min(sums) - 0.01
    xs = [s - shift for s in sums]  # strictly positive
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / max(1, len(xs) - 1)
    if var <= 0:
        return [0.0] * len(sums)
    # log-logistic parameters via method of moments on log(x)
    logs = [math.log(x) for x in xs]
    lmean = sum(logs) / len(logs)
    lvar = sum((l - lmean) ** 2 for l in logs) / max(1, len(logs) - 1)
    beta = math.pi / (math.sqrt(3 * lvar)) if lvar > 0 else 3.6
    alpha = math.exp(lmean + 0.5772 / beta)  # Euler-Mascheroni adjustment
    out = []
    for s in sums:
        x = s - shift
        f = 1.0 / (1.0 + (alpha / x) ** beta) if x > 0 else 1e-6
        f = min(max(f, 1e-6), 1 - 1e-6)
        out.append(round(_norm_ppf(f), 2))
    return out


# ---------- agrometeorology ----------

def _hargreaves_pet(tmax, tmin, lat, day_of_year):
    """FAO-56 Hargreaves PET (mm/day), eq. 50 — needs only Tmax/Tmin + lat."""
    phi = math.radians(lat)
    j = day_of_year
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    delta = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    arg = -math.tan(phi) * math.tan(delta)
    ws = math.acos(max(-1.0, min(1.0, arg)))
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(delta) +
        math.cos(phi) * math.cos(delta) * math.sin(ws))
    tmean = (tmax + tmin) / 2
    return max(0.0, 0.0023 * (tmean + 17.8) * math.sqrt(max(0.0, tmax - tmin)) * ra)


def _meta(formula, unit, source, reference, limitations):
    return {'formula': formula, 'unit': unit, 'source': source,
            'reference_period': reference, 'limitations': limitations}


# ---------- main entry ----------

def get_climate_indicators(lat, lon, start=None, end=None):
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Latitude/longitude out of range')
    end_d = date.today()
    start_d = end_d - timedelta(days=MAX_DAYS)
    if start:
        start_d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    if end:
        end_d = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    if (end_d - start_d).days > MAX_DAYS:
        raise ValueError(f'Climate analysis supports up to {MAX_DAYS} days (~5 years)')
    if start_d >= end_d:
        raise ValueError('Start date must be before end date')

    power = fetch_power(lat, lon, start_d.strftime('%Y%m%d'), end_d.strftime('%Y%m%d'),
                        POWER_PARAMS, community='AG', temporal='daily')
    dates = power.get('dates', [])
    maps = {}
    for p in power.get('parameters', []):
        maps[p['code']] = {pt['date']: pt['value'] for pt in p['points']}
    if not dates:
        raise ValueError('NASA POWER returned no data for this location/period')

    # daily series aligned to dates
    tmax = [maps.get('T2M_MAX', {}).get(d) for d in dates]
    tmin = [maps.get('T2M_MIN', {}).get(d) for d in dates]
    t2m = [maps.get('T2M', {}).get(d) for d in dates]
    rain = [maps.get('PRECTOTCORR', {}).get(d) for d in dates]

    # monthly aggregation
    months = defaultdict(lambda: {'tmax': [], 'tmin': [], 't2m': [], 'rain': 0.0, 'pet': 0.0, 'n': 0})
    for i, d in enumerate(dates):
        key = d[:6]  # YYYYMM
        m = months[key]
        tx, tn = tmax[i], tmin[i]
        if tx is not None and tn is not None:
            doy = date(int(d[:4]), int(d[4:6]), int(d[6:8])).timetuple().tm_yday
            m['pet'] += _hargreaves_pet(tx, tn, lat, doy)
        if t2m[i] is not None:
            m['t2m'].append(t2m[i])
        if tx is not None:
            m['tmax'].append(tx)
        if tn is not None:
            m['tmin'].append(tn)
        if rain[i] is not None:
            m['rain'] += rain[i]
        m['n'] += 1

    monthly = []
    for key in sorted(months):
        m = months[key]
        monthly.append({
            'month': f'{key[:4]}-{key[4:]}',
            'tmean_c': round(sum(m['t2m']) / len(m['t2m']), 2) if m['t2m'] else None,
            'tmax_c': round(sum(m['tmax']) / len(m['tmax']), 2) if m['tmax'] else None,
            'tmin_c': round(sum(m['tmin']) / len(m['tmin']), 2) if m['tmin'] else None,
            'precip_mm': round(m['rain'], 1),
            'pet_mm': round(m['pet'], 1),
            'water_balance_mm': round(m['rain'] - m['pet'], 1),
        })

    precip_series = [m['precip_mm'] for m in monthly]
    wb_series = [m['water_balance_mm'] for m in monthly]
    tmean_series = [m['tmean_c'] for m in monthly if m['tmean_c'] is not None]

    ref = f"{start_d.isoformat()} to {end_d.isoformat()} ({len(monthly)} months, NASA POWER daily → monthly)"

    # --- anomalies (last 12 months vs full-period mean) ---
    indicators = {}
    last12_t = tmean_series[-12:]
    last12_p = precip_series[-12:]
    if tmean_series and last12_t:
        full_mean = sum(tmean_series) / len(tmean_series)
        indicators['temperature_anomaly_c'] = {
            'value': round(sum(last12_t) / len(last12_t) - full_mean, 2),
            'unit': '°C', **_meta('Tmean(last 12m) − Tmean(full period)', '°C',
                                   'NASA POWER T2M', ref,
                                   'Anomaly vs the fetched period only; not a climate-normal baseline.')}
    if precip_series and last12_p:
        full_mean = sum(precip_series) / len(precip_series)
        indicators['precipitation_anomaly_pct'] = {
            'value': round((sum(last12_p) / len(last12_p) - full_mean) / full_mean * 100, 1) if full_mean else None,
            'unit': '%', **_meta('(P_last12m − P_mean) / P_mean × 100', '%',
                                 'NASA POWER PRECTOTCORR', ref,
                                 'Percentage anomaly; sensitive when the period mean is near zero.')}

    # --- SPI / SPEI ---
    for scale in (1, 3, 6, 12):
        spi = _spi_series(precip_series, scale)
        spei = _spei_series(wb_series, scale)
        indicators[f'spi_{scale}m'] = {
            'value': spi[-1] if spi else None,
            'series': spi,
            'unit': 'dimensionless',
            **_meta(f'SPI-{scale}: gamma fit (method of moments) on {scale}-month precipitation sums, '
                    'mapped via inverse normal CDF', 'dimensionless', 'NASA POWER PRECTOTCORR', ref,
                    f'Needs ≥{scale + 5} months; computed on {len(precip_series)} months. '
                    'Classification: |SPI|<1 normal, 1-1.5 moderate, 1.5-2 severe, >2 extreme (WMO).')}
        indicators[f'spei_{scale}m'] = {
            'value': spei[-1] if spei else None,
            'series': spei,
            'unit': 'dimensionless',
            **_meta(f'SPEI-{scale}: log-logistic fit on shifted {scale}-month water balance '
                    '(P − PET_Hargreaves), inverse normal CDF', 'dimensionless',
                    'NASA POWER PRECTOTCORR + Hargreaves PET (FAO-56 eq.50)', ref,
                    'Approximation: log-logistic via method of moments on log-values with shift; '
                    'PET is Hargreaves (temperature-based), not full Penman-Monteith.')}

    # --- extremes ---
    heat_days = sum(1 for v in tmax if v is not None and v >= 35)
    frost_days = sum(1 for v in tmin if v is not None and v <= 0)
    # heatwave events: >=3 consecutive days Tmax>=35
    events = 0
    run = 0
    for v in tmax:
        if v is not None and v >= 35:
            run += 1
        else:
            if run >= 3:
                events += 1
            run = 0
    if run >= 3:
        events += 1
    # max consecutive dry days (<1 mm)
    best = cur = 0
    for v in rain:
        if v is not None and v < 1.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    # GDD base 10
    gdd = 0.0
    for i in range(len(dates)):
        if tmax[i] is not None and tmin[i] is not None:
            gdd += max(0.0, (tmax[i] + tmin[i]) / 2 - 10)

    indicators['heatwave'] = {
        'value': {'days_ge35c': heat_days, 'events_ge3days': events},
        'unit': 'days/events',
        **_meta('Days with Tmax≥35°C; events = runs of ≥3 consecutive such days', 'days',
                'NASA POWER T2M_MAX', ref,
                'Fixed 35°C threshold; region-specific heat thresholds may differ.')}
    indicators['frost_days'] = {
        'value': frost_days, 'unit': 'days',
        **_meta('Days with Tmin≤0°C', 'days', 'NASA POWER T2M_MIN', ref,
                'Radiation frost can occur with Tmin slightly above 0°C.')}
    indicators['max_consecutive_dry_days'] = {
        'value': best, 'unit': 'days',
        **_meta('Longest run of days with precipitation <1 mm', 'days',
                'NASA POWER PRECTOTCORR', ref,
                'Missing data days break the run; does not account for soil moisture carry-over.')}
    indicators['gdd_base10'] = {
        'value': round(gdd, 1), 'unit': '°C·day',
        **_meta('Σ max(0, (Tmax+Tmin)/2 − 10°C) over daily values', '°C·day',
                'NASA POWER T2M_MAX/T2M_MIN', ref,
                'Generic base 10°C; crop-specific GDD uses per-crop base temperature (see advisor).')}
    indicators['water_balance'] = {
        'value': round(sum(wb_series), 1), 'unit': 'mm',
        **_meta('Σ(P_monthly − PET_Hargreaves_monthly) over the period', 'mm',
                'NASA POWER + Hargreaves PET', ref,
                'Positive = water surplus; negative = deficit. PET is temperature-based approximation.')}

    return {
        'source': 'NASA POWER',
        'fetched_at': power.get('fetched_at'),
        'location': {'lat': lat, 'lon': lon},
        'period': {'start': start_d.isoformat(), 'end': end_d.isoformat(),
                   'days': len(dates), 'months': len(monthly)},
        'reference': ref,
        'indicators': indicators,
        'monthly': monthly,
        'limitations': [
            'SPI/SPEI computed on monthly aggregates of daily POWER data; '
            'operational drought monitoring typically uses ≥30-year records.',
            'SPEI uses Hargreaves PET (temperature-based) — not full FAO-56 Penman-Monteith.',
            'Anomalies are relative to the fetched period, not long-term climate normals.',
        ],
    }
