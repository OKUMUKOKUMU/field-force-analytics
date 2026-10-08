"""Visit verification, merchandiser compliance scoring and FIFO freshness alerts.

The analytics layer of a field force automation platform:
- Geofence check: haversine distance from check-in to the outlet vs its geofence radius
- Duration check: visits shorter than MIN_VISIT_MIN are suspect
- Evidence check: photo count and manager sign-off
- A visit failing the geofence, or failing two other checks, is a probable ghost visit
- Compliance score per merchandiser, and a FIFO / near-expiry alert list per outlet

Usage: python verify_visits.py   (run generate_data.py first)
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)
MIN_VISIT_MIN = 10
MIN_PHOTOS = 2
AS_OF = pd.Timestamp("2026-08-25")
NEAR_EXPIRY_DAYS = 5


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6_371_000
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlmb = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def verify(visits: pd.DataFrame, outlets: pd.DataFrame) -> pd.DataFrame:
    v = visits.merge(outlets, on="outlet_id")
    v["distance_m"] = haversine_m(v.checkin_lat, v.checkin_lon, v.lat, v.lon).round(1)
    v["duration_min"] = (pd.to_datetime(v.check_out) - pd.to_datetime(v.check_in)).dt.total_seconds() / 60
    v["fail_geofence"] = v.distance_m > v.geofence_m
    v["fail_duration"] = v.duration_min < MIN_VISIT_MIN
    v["fail_evidence"] = v.photos < MIN_PHOTOS
    v["fail_signoff"] = ~v.manager_signoff.astype(bool)
    soft = v[["fail_duration", "fail_evidence", "fail_signoff"]].sum(axis=1)
    v["ghost_visit"] = v.fail_geofence | (soft >= 2)
    return v


def compliance(v: pd.DataFrame) -> pd.DataFrame:
    s = v.groupby("merchandiser_id").agg(
        visits=("visit_id", "count"), ghost_rate=("ghost_visit", "mean"),
        geofence_fail_rate=("fail_geofence", "mean"), avg_duration_min=("duration_min", "mean"),
        outlets_covered=("outlet_id", "nunique"))
    s["compliance_score"] = (100 * (1 - s.ghost_rate)).round(1)
    s["status"] = pd.cut(s.compliance_score, [-1, 85, 95, 101], labels=["Investigate", "Coach", "Good"])
    return s.sort_values("compliance_score")


def freshness_alerts(b: pd.DataFrame) -> pd.DataFrame:
    b = b[b.qty_on_shelf > 0].copy()
    b["expiry"] = pd.to_datetime(b.expiry)
    b["received"] = pd.to_datetime(b.received)
    b["days_to_expiry"] = (b.expiry - AS_OF).dt.days
    b = b.sort_values(["outlet_id", "sku", "received"])
    b["fifo_rank"] = b.groupby(["outlet_id", "sku"]).cumcount() + 1
    b["batches_on_shelf"] = b.groupby(["outlet_id", "sku"]).sku.transform("size")
    b["alert"] = np.select(
        [b.days_to_expiry < 0, b.days_to_expiry <= NEAR_EXPIRY_DAYS, (b.fifo_rank == 1) & (b.batches_on_shelf > 1)],
        ["EXPIRED - pull from shelf", "NEAR EXPIRY - rotate to front / return", "FIFO - oldest batch to front"],
        default="")
    return b[b.alert != ""].sort_values("days_to_expiry")


def charts(v: pd.DataFrame, s: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(v.distance_m.clip(upper=1500), bins=60, color="#0f766e")
    ax.axvline(150, color="#b45309", ls="--", label="largest geofence (150 m)")
    ax.set_xlabel("Check-in distance from outlet (m, capped at 1,500)"); ax.set_ylabel("Visits")
    ax.set_title("Most check-ins sit inside the geofence; the long tail is ghost-visit risk")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "checkin_distance.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    col = s.status.map({"Investigate": "#b45309", "Coach": "#f59e0b", "Good": "#0f766e"})
    ax.bar(s.index, s.compliance_score, color=col)
    ax.set_ylim(min(60, s.compliance_score.min() - 5), 100)
    ax.set_ylabel("Compliance score"); ax.set_title("Merchandiser compliance (orange = investigate)")
    ax.tick_params(axis="x", rotation=90, labelsize=7); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "merchandiser_compliance.png", dpi=150); plt.close(fig)


def main() -> None:
    outlets = pd.read_csv(ROOT / "data" / "outlets.csv")
    visits = pd.read_csv(ROOT / "data" / "visits.csv")
    batches = pd.read_csv(ROOT / "data" / "shelf_batches.csv")
    v = verify(visits, outlets)
    s = compliance(v)
    alerts = freshness_alerts(batches)
    v[v.ghost_visit].to_csv(OUT / "flagged_visits.csv", index=False)
    s.to_csv(OUT / "merchandiser_compliance.csv")
    alerts.to_csv(OUT / "freshness_alerts.csv", index=False)
    charts(v, s)
    print(f"Visits checked:      {len(v):,}")
    print(f"Probable ghost visits: {v.ghost_visit.sum():,} ({v.ghost_visit.mean():.1%})")
    print(f"Merchandisers to investigate: {(s.status == 'Investigate').sum()}")
    print("Freshness alerts:\n" + alerts.alert.value_counts().to_string())


if __name__ == "__main__":
    main()
