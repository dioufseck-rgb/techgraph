"""Representative days for Dominion's zone.

Load: Dominion zone hourly load for 2017 from the public PJM hourly archive (DOM_hourly.csv).
      Four typical seasonal days (closest to each season's mean profile) plus the winter-peak and
      summer-peak days, weighted to 365 days. Shapes are normalized to the 2017 annual peak.
Solar: pvlib clear-sky irradiance at 37.5N, 77.4W, scaled by a seasonal clearness factor and
       calibrated to an annual yield of about 1,500 kWh per kW.
Offshore wind: hourly shapes from the GenX New England example for the same calendar days,
       rescaled to seasonal capacity factors typical of mid-Atlantic offshore wind (proxy).
"""
import json
import numpy as np
import pandas as pd
import pvlib

LOAD_CSV = '/home/claude/DOM_hourly.csv'
GENX_VAR = '/home/claude/genx_repo/example_systems/1_three_zones/system/Generators_variability.csv'
SEASONS = {'winter': (12, 1, 2), 'spring': (3, 4, 5), 'summer': (6, 7, 8), 'fall': (9, 10, 11)}
CLEARNESS = {'winter': 0.62, 'spring': 0.70, 'summer': 0.72, 'fall': 0.68}       # assumption
OSW_CF = {'winter': 0.55, 'spring': 0.45, 'summer': 0.30, 'fall': 0.45}          # assumption
PEAK_WEIGHT = 3.0


def build(year=2017, target_yield=1500.0):
    d = pd.read_csv(LOAD_CSV, parse_dates=['Datetime']).drop_duplicates('Datetime').set_index('Datetime').sort_index()
    d = d[d.index.year == year]
    d.index = d.index - pd.Timedelta(hours=1)                 # hour-ending to hour-beginning
    daily = d.DOM_MW.groupby(d.index.date).apply(lambda s: s.values if len(s) == 24 else None).dropna()
    days = pd.DataFrame({'date': pd.to_datetime(daily.index), 'prof': daily.values})
    peak = d.DOM_MW.max()
    days['month'] = days.date.dt.month
    days['max'] = days.prof.apply(max)
    wpk = days[days.month.isin(SEASONS['winter'])].sort_values('max').iloc[-1]
    spk = days[days.month.isin(SEASONS['summer'])].sort_values('max').iloc[-1]
    snap = [wpk.date - pd.Timedelta(days=2), wpk.date - pd.Timedelta(days=1), wpk.date]   # three-day cold snap ending on the peak day
    chosen, weights = [], []
    for s, months in SEASONS.items():
        sub = days[days.month.isin(months)]
        mean = np.mean(np.stack(sub.prof.values), axis=0)
        i = np.argmin([np.sum((p - mean) ** 2) for p in sub.prof.values])
        n = len(sub) - (PEAK_WEIGHT if s in ('winter', 'summer') else 0)
        chosen.append((s, sub.iloc[i].date)); weights.append(n)
    chosen += [('winter snap 1', snap[0]), ('winter snap 2', snap[1]), ('winter snap 3', snap[2]), ('summer peak', spk.date)]
    weights += [1.0, 1.0, 1.0, PEAK_WEIGHT]
    scale = 365.0 / sum(weights)
    weights = [w * scale for w in weights]
    load = []
    for _, dt in chosen:
        load += list(days[days.date == dt].prof.iloc[0] / peak)
    # solar
    loc = pvlib.location.Location(37.5, -77.4, tz='America/New_York')
    solar = []
    for (label, dt) in chosen:
        season = label.split()[0]
        times = pd.date_range(dt, periods=24, freq='h', tz='America/New_York') + pd.Timedelta(minutes=30)
        cs = loc.get_clearsky(times)
        solar += list(np.clip(cs['ghi'].values / 1000.0 * CLEARNESS[season], 0, 1))
    W = np.repeat(weights, 24)
    yield_now = float(np.sum(W * np.array(solar)))
    solar = list(np.clip(np.array(solar) * target_yield / yield_now, 0, 1))
    # offshore wind proxy
    g = pd.read_csv(GENX_VAR)
    wind = []
    for (label, dt) in chosen:
        season = label.split()[0]
        doy = min(dt.dayofyear - 1, 364)
        w = g.CT_onshore_wind.values[doy * 24:(doy + 1) * 24]
        w = np.clip(w * OSW_CF[season] / max(1e-6, w.mean()), 0, 1)
        wind += list(w)
    blocks = [(0, 24), (24, 24), (48, 24), (72, 24), (96, 72), (168, 24)]      # the cold snap cycles as one 72-hour block
    out = dict(days=[(l, str(dt.date())) for l, dt in chosen], day_weights=weights, load=load, solar=solar, wind=wind, blocks=blocks,
               period_weights=[float(x) for x in W], peak_2017=float(peak),
               solar_yield_kwh_per_kw=float(np.sum(W * np.array(solar))),
               wind_cf=float(np.sum(W * np.array(wind)) / 8760))
    return out


if __name__ == '__main__':
    p = build()
    json.dump(p, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'va_days2.json'), 'w'))
    print(p['days']); print([round(w, 1) for w in p['day_weights']])
    print('solar yield', round(p['solar_yield_kwh_per_kw']), 'wind CF', round(p['wind_cf'], 3))
    for k in range(len(p['days'])):
        seg = p['load'][24 * k:24 * k + 24]
        print(p['days'][k][0], 'load min/max', round(min(seg), 2), round(max(seg), 2), 'peak hour', int(np.argmax(seg)),
              'solar max', round(max(p['solar'][24 * k:24 * k + 24]), 2))
