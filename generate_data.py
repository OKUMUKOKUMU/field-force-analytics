"""Synthetic retail outlets, merchandiser visits and stock batches for Kenya.

Includes deliberately planted "ghost visits" (check-ins far from the outlet,
implausibly short visits, missing photo evidence) so the verification logic
has something to find. No real data is included.
Usage: python generate_data.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(7)
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

TOWNS = {"Nairobi": (-1.286, 36.817), "Mombasa": (-4.043, 39.668), "Kisumu": (-0.092, 34.768),
         "Nakuru": (-0.303, 36.080), "Eldoret": (0.514, 35.270), "Nyeri": (-0.420, 36.947)}

# Outlets
outlets = []
for town, (lat, lon) in TOWNS.items():
    for i in range(RNG.integers(20, 45)):
        outlets.append(dict(outlet_id=f"{town[:3].upper()}-{i:03d}", town=town,
                            lat=lat + RNG.normal(0, .03), lon=lon + RNG.normal(0, .03),
                            geofence_m=int(RNG.choice([75, 100, 150]))))
outlets = pd.DataFrame(outlets)

# Merchandisers (a few behave badly)
mers = pd.DataFrame({"merchandiser_id": [f"M{i:02d}" for i in range(1, 43)]})
mers["town"] = RNG.choice(list(TOWNS), len(mers))
mers["risk"] = RNG.choice([0.02, 0.05, 0.25], len(mers), p=[.6, .3, .1])

# Visits over 8 weeks
visits = []
dates = pd.date_range("2026-07-01", "2026-08-25", freq="B")
for _, m in mers.iterrows():
    pool = outlets[outlets.town == m.town]
    for d in dates:
        for o in pool.sample(int(RNG.integers(5, 9)), random_state=int(RNG.integers(1e9))).itertuples():
            ghost = RNG.random() < m.risk
            dist = RNG.uniform(400, 4000) if ghost and RNG.random() < .6 else abs(RNG.normal(0, o.geofence_m * .4))
            bearing = RNG.uniform(0, 2 * np.pi)
            dlat = dist * np.cos(bearing) / 111_320
            dlon = dist * np.sin(bearing) / (111_320 * np.cos(np.radians(o.lat)))
            start = d + pd.Timedelta(hours=float(RNG.uniform(8, 16)))
            dur = RNG.uniform(1, 5) if ghost and RNG.random() < .5 else RNG.uniform(15, 55)
            visits.append(dict(visit_id=f"V{len(visits):06d}", merchandiser_id=m.merchandiser_id,
                               outlet_id=o.outlet_id, check_in=start.round("s"),
                               check_out=(start + pd.Timedelta(minutes=float(dur))).round("s"),
                               checkin_lat=o.lat + dlat, checkin_lon=o.lon + dlon,
                               photos=0 if ghost and RNG.random() < .5 else int(RNG.integers(2, 7)),
                               manager_signoff=not (ghost and RNG.random() < .7)))
visits = pd.DataFrame(visits)

# Stock batches on shelf for the freshness ledger
SKUS = [f"SKU-{i:03d}" for i in range(1, 61)]
batches = []
for o in outlets.sample(80, random_state=1).itertuples():
    for sku in RNG.choice(SKUS, 6, replace=False):
        for b in range(RNG.integers(1, 4)):
            received = pd.Timestamp("2026-08-01") + pd.Timedelta(days=int(RNG.integers(-20, 20)))
            shelf_life = int(RNG.choice([10, 21, 45, 120]))
            batches.append(dict(outlet_id=o.outlet_id, sku=sku, batch_no=f"B{RNG.integers(1e5, 1e6)}",
                                received=received.date(), expiry=(received + pd.Timedelta(days=shelf_life)).date(),
                                qty_on_shelf=int(RNG.integers(0, 60))))
batches = pd.DataFrame(batches)

outlets.to_csv(OUT / "outlets.csv", index=False)
mers.drop(columns="risk").to_csv(OUT / "merchandisers.csv", index=False)
visits.to_csv(OUT / "visits.csv", index=False)
batches.to_csv(OUT / "shelf_batches.csv", index=False)
print(f"{len(outlets)} outlets, {len(mers)} merchandisers, {len(visits):,} visits, {len(batches)} batches")
