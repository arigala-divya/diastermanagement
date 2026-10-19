"""Turn a change summary into NORMAL / WATCH / ALERT, with stated reasons.

Every level carries the human-readable rule that produced it, so an alert can
always be explained ("31.4 km2 new water >= 20 km2 threshold").
"""

LEVELS = ("NORMAL", "WATCH", "ALERT")


def evaluate(summary: dict, t: dict) -> tuple[str, list[str]]:
    new = summary["new_water_km2"]
    pct = summary["increase_pct"]
    patch = summary["largest_patch_km2"]
    min_pct_km2 = t.get("min_pct_km2", 1)

    alert, watch = [], []
    if new >= t["alert_km2"]:
        alert.append(f"{new:.1f} km² new water ≥ {t['alert_km2']} km²")
    if pct >= t["alert_increase_pct"] and new >= max(min_pct_km2, t["watch_km2"]):
        alert.append(f"water extent +{pct:.0f}% ≥ {t['alert_increase_pct']}%")
    if alert and patch < t["min_patch_km2"]:
        watch.append(f"alert criteria met but largest patch {patch:.1f} km² < "
                     f"{t['min_patch_km2']} km² (fragmented change)")
        alert = []
    if alert:
        return "ALERT", alert

    if new >= t["watch_km2"]:
        watch.append(f"{new:.1f} km² new water ≥ {t['watch_km2']} km²")
    if pct >= t["watch_increase_pct"] and new >= min_pct_km2:
        watch.append(f"water extent +{pct:.0f}% ≥ {t['watch_increase_pct']}%")
    if watch:
        return "WATCH", watch
    return "NORMAL", [f"{new:.1f} km² new water, below thresholds"]
