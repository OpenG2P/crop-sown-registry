"""Sample crop seasons for a demo install, built from Master Data's sample people.

The Farmer Registry and the Crop Sown Registry are independent, yet a demo
should show the *same* farmers and plots in both. Neither reads the other's
database; both derive identifiers from the same source, Master Data's sample
people (the country pack's ``samples/individuals.json``), by shared conventions:

* **farmer:** sample person ``ETH-IND-0007`` is farmer ``FR-0007`` (the Farmer
  Registry's rule), with the person's national ID as the Fayda FAN;
* **plots:** that person's sample plots are ``LAND-0007-1``, ``LAND-0007-2``…, in
  the person's woreda (the Farmer Registry numbers a sample person's lands this
  way). Here, every adult farms plot 1, and every third also plot 2.

The samples cover past and current seasons at every stage — planned, prepared,
sown, observed, an infestation, a drought, harvested — with most sowings and
harvests verified, one corrected, and farmers in the two sample clusters' woredas
enrolled in them. Dates are fixed, so a reinstall produces the same data.
"""

from datetime import datetime
from typing import Optional

from openg2p_registry_core.schemas.activity import ActivityInput
from openg2p_registry_core.services import SampleStep

REGISTER = "CropSown"

# Crop, its usual variety, and a plausible yield (qt/ha), by farmer.
CROPS = [
    ("CROP_TEFF", "VAR_TEFF_QUNCHO", 18),
    ("CROP_WHEAT", "VAR_WHEAT_KAKABA", 30),
    ("CROP_MAIZE", "VAR_MAIZE_BH661", 40),
    ("CROP_SORGHUM", "VAR_SORGHUM_MELKAM", 25),
    ("CROP_BARLEY", "VAR_BARLEY_HB1307", 22),
]

# (crop year, season, dates of each stage). The past Meher season is complete;
# the Belg season is complete for some farmers; the current Meher season is
# growing, so its harvests fall due on the work list.
SEASONS = {
    "meher_2018": (2018, "SEASON_MEHER", {
        "PLANNED": "2025-05-15", "CLUSTER_ENROLLED": "2025-05-30", "LAND_PREPARED": "2025-06-02",
        "SOWN": "2025-06-25", "GROWTH_OBSERVED": "2025-08-20", "INFESTATION_REPORTED": "2025-09-04",
        "HARVESTED": "2025-11-20"}),
    "belg_2018": (2018, "SEASON_BELG", {
        "PLANNED": "2026-01-20", "SOWN": "2026-02-24", "GROWTH_OBSERVED": "2026-04-15",
        "DAMAGE_REPORTED": "2026-05-10", "HARVESTED": "2026-07-08"}),
    "meher_2019": (2019, "SEASON_MEHER", {
        "PLANNED": "2026-05-12", "LAND_PREPARED": "2026-06-01", "SOWN": "2026-06-28",
        "GROWTH_OBSERVED": "2026-09-05"}),
}


def farmer_number(individual_id: str) -> str:
    """ETH-IND-0007 → 0007 (the Farmer Registry's rule)."""
    return str(individual_id).rsplit("-", 1)[-1]


def plot_ids(number: str) -> list[str]:
    return [f"LAND-{number}-1"] + ([f"LAND-{number}-2"] if int(number) % 3 == 0 else [])


def build_steps(people: list[dict], clusters: Optional[dict[str, tuple[str, Optional[str]]]] = None
                ) -> list[SampleStep]:
    """Sample steps for adult sample people. ``people`` rows: individual_id, age, national_id, geo_pcode.

    ``clusters`` maps a woreda to the Cluster register's cluster there, as
    (Cluster ID, crop): read from the register (db-seed loads the sample clusters),
    so the generated Cluster IDs are never assumed. A farmer in a cluster's woreda
    grows the cluster's crop on plot 1, and enrols it.
    """
    clusters = clusters or {}
    steps: list[SampleStep] = []
    corrected = False
    for person in sorted(people, key=lambda p: p["individual_id"]):
        if (person.get("age") or 0) < 18 or not person.get("geo_pcode"):
            continue
        number = farmer_number(person["individual_id"])
        seq = int(number)
        fan = str(person.get("national_id") or "").strip()
        base = {
            "farmer_id": f"FR-{number}",
            **({"fayda_fan": fan} if fan.isdigit() and 12 <= len(fan) <= 16 else {}),
            "geo_lowest_level_value_id": person["geo_pcode"],
            "da_id": f"DA-{person['geo_pcode']}",
        }
        cluster, cluster_crop = clusters.get(person["geo_pcode"], (None, None))
        if cluster_crop and not any(c[0] == cluster_crop for c in CROPS):
            cluster_crop = None  # a crop the samples have no variety for: the farmer's own rotation
        for plot_index, plot in enumerate(plot_ids(number)):
            crop, variety, crop_yield = CROPS[(seq + plot_index) % len(CROPS)]
            if cluster_crop and plot_index == 0:
                crop, variety, crop_yield = next(c for c in CROPS if c[0] == cluster_crop)
            planned_area = round(0.5 + (seq % 4) * 0.25, 2)
            sown_area = round(planned_area * 0.9, 2)
            verify = seq % 5 != 0  # every fifth farmer's sowings and harvests await verification
            for name, (crop_year, season, dates) in SEASONS.items():
                if name == "belg_2018" and (plot_index or seq % 2):
                    continue  # Belg: plot 1 of every other farmer
                key = f"sample:{number}:{plot}:{name}"
                context = {**base, "plot_id": plot, "crop_year": crop_year, "season": season, "crop": crop}

                def add(kind: str, **payload) -> SampleStep:
                    step = SampleStep(ActivityInput(
                        register_mnemonic=REGISTER, activity_type=kind, idempotency_key=f"{key}:{kind}",
                        occurred_at=datetime.fromisoformat(dates[kind]),
                        payload={**context, **payload},
                    ), verify=verify)
                    steps.append(step)
                    return step

                add("PLANNED", area_ha=planned_area, variety=variety, cropping_system="CSYS_PURE",
                    expected_yield_qt_per_ha=crop_yield)
                if "CLUSTER_ENROLLED" in dates and cluster and plot_index == 0:
                    add("CLUSTER_ENROLLED", cluster_id=cluster)
                if "LAND_PREPARED" in dates:
                    add("LAND_PREPARED", preparation_method="LPM_OXEN" if seq % 2 else "LPM_TRACTOR",
                        area_ha=planned_area, soil_fertility="SF_MEDIUM")
                sown = add("SOWN", area_ha=sown_area, variety=variety, seed_type="SEED_IMPROVED" if seq % 2
                           else "SEED_LOCAL", seed_source="SEEDSRC_COOPERATIVE", seed_kg=round(sown_area * 20, 1),
                           sowing_method="SOW_ROW", cropping_system="CSYS_PURE",
                           fertilizers=[{"fertilizer_type": "FERT_NPS", "quantity_kg": round(sown_area * 100)}])
                if not corrected and name == "meher_2018":
                    # One sowing re-measured after the fact: the correction supersedes it.
                    sown.correction = {"reason": "Sample: area re-measured by the DA",
                                       "payload": {"area_ha": round(sown_area + 0.1, 2)}}
                    corrected = True
                add("GROWTH_OBSERVED", growth_stage="GS_FLOWERING" if name == "meher_2019" else "GS_GRAIN_FILLING",
                    crop_condition="CC_GOOD" if seq % 3 else "CC_FAIR", area_ha=sown_area)
                if "INFESTATION_REPORTED" in dates and seq % 3 == 0:
                    add("INFESTATION_REPORTED", infestation_type="INFT_PEST", agent="AGENT_FALL_ARMYWORM",
                        severity="SEV_MEDIUM", area_ha=round(sown_area / 3, 2), damage_percent=10,
                        action_taken="CTRL_CHEMICAL")
                if "DAMAGE_REPORTED" in dates and seq % 4 == 0:
                    add("DAMAGE_REPORTED", cause="DMG_DROUGHT", loss_percent=30, area_ha=sown_area)
                if "HARVESTED" in dates:
                    factor = 0.7 if ("DAMAGE_REPORTED" in dates and seq % 4 == 0) else 0.8 + (seq % 3) * 0.1
                    quantity = round(sown_area * crop_yield * factor, 1)
                    add("HARVESTED", area_ha=sown_area, quantity_qt=quantity, stored_qt=round(quantity * 0.4, 1),
                        sold_qt=round(quantity * 0.4, 1), consumed_qt=round(quantity * 0.2, 1))
    for step in steps:
        if step.activity.activity_type not in ("SOWN", "HARVESTED"):
            step.verify = False  # only these require verification
    return steps
