#!/usr/bin/env python3
"""End-to-end smoke test of a running Crop Sown Registry through its partner API.

Records one crop season (plan → prepare → sow → observe → infestation →
harvest) as a partner, checks idempotency and a blocked out-of-order activity,
then reads the activities back with DCI search.

    python3 scripts/e2e_smoke.py --partner-url http://localhost:18006 [--db-url postgresql://...]

With --db-url it also checks, in the registry database, the crop-season
projection and that the Celery outbox worker processed the events.

The partner API must accept unsigned requests (hybrid run) or you pass
--signature for a pre-signed body; the Helm install enforces signatures.
Only the standard library is used (plus psycopg if --db-url is given).
"""

import argparse
import json
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

REG = "CropSown"
# The plot's woreda (Sheno town, North Shewa (OR), Oromia) in the ETH pack Master Data holds.
WOREDA = "ET040611"


def dci_search(signature, now, record_type: str, farmer_id: str) -> dict:
    """A DCI search on the CropSown register by farmer ID. The record type picks activities
    (spdci-extensions-agri:CropActivity) or the farmer's aggregates (…:ActivityAggregate)."""
    return {
        "signature": signature or "",
        "header": {"version": "1.0.0", "message_id": str(uuid.uuid4()), "message_ts": now.isoformat(),
                   "action": "search", "sender_id": "csr-smoke-test", "receiver_id": "crop-sown-registry",
                   "total_count": 1},
        "message": {"transaction_id": str(uuid.uuid4()), "search_request": [{
            "reference_id": "1", "timestamp": now.isoformat(),
            "search_criteria": {"reg_type": REG, "reg_record_type": record_type,
                                "query_type": "idtype-value",
                                "query": {"type": "idtype-value", "value": {"id_type": "farmer_id",
                                                                            "id_value": farmer_id}},
                                "pagination": {"page_size": 20, "page_number": 1}},
        }]},
    }


def post(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def envelope(activities: list[dict], signature: str | None = None) -> dict:
    return {
        "signature": signature,
        "header": {"sender_id": "csr-smoke-test", "message_id": str(uuid.uuid4()),
                   "message_ts": datetime.now(timezone.utc).isoformat()},
        "message": {"activities": activities, "atomic": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partner-url", required=True)
    parser.add_argument("--db-url")
    parser.add_argument("--signature")
    args = parser.parse_args()
    base = args.partner_url.rstrip("/")
    run = uuid.uuid4().hex[:8].upper()
    plot = f"LND-SMOKE-{run}"
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def activity(kind: str, days_ago: int, **payload) -> dict:
        return {
            "register_mnemonic": REG,
            "activity_type": kind,
            "occurred_at": (now - timedelta(days=days_ago)).isoformat(),
            "idempotency_key": f"smoke:{run}:{kind}",
            "payload": {"farmer_id": f"FR-SMOKE-{run}", "plot_id": plot, "crop_year": 2019,
                        "season": "SEASON_MEHER", "crop": "CROP_TEFF",
                        "geo_lowest_level_value_id": WOREDA, **payload},
        }

    # Codes are Master Data's (ETH pack, agriculture domain).
    season = [
        activity("PLANNED", 110, area_ha=1.0, variety="VAR_TEFF_QUNCHO", cropping_system="CSYS_PURE"),
        activity("LAND_PREPARED", 105, preparation_method="LPM_OXEN", soil_fertility="SF_MEDIUM"),
        activity("SOWN", 100, area_ha=0.9, seed_type="SEED_IMPROVED", seed_source="SEEDSRC_COOPERATIVE",
                 sowing_method="SOW_ROW", fertilizers=[{"fertilizer_type": "FERT_NPS", "quantity_kg": 100}]),
        activity("GROWTH_OBSERVED", 55, growth_stage="GS_VEGETATIVE", crop_condition="CC_GOOD", area_ha=0.9),
        activity("INFESTATION_REPORTED", 45, infestation_type="INFT_PEST", agent="AGENT_FALL_ARMYWORM",
                 severity="SEV_MEDIUM", area_ha=0.2, action_taken="CTRL_CHEMICAL"),
        activity("HARVESTED", 2, area_ha=0.9, quantity_qt=15.3, stored_qt=8, sold_qt=5, consumed_qt=2),
    ]
    failures = []

    def check(condition: bool, message: str):
        print(("  ok   " if condition else "  FAIL ") + message)
        if not condition:
            failures.append(message)

    print(f"Recording a crop season for plot {plot}")
    result = post(f"{base}/partner/activity/append_activities", envelope(season, args.signature))
    outcomes = [r["outcome"] for r in result.get("results", [])]
    check(result.get("status") == "SUCCESS" and outcomes == ["CREATED"] * 6, f"six activities created ({outcomes})")
    harvest = result["results"][-1].get("activity") or {}
    check(harvest.get("payload", {}).get("yield_qt_per_ha") == 17.0, "yield derived on the harvest (17 qt/ha)")
    check(result["results"][2]["activity"]["verification_status"] == "SUBMITTED", "sowing awaits verification")

    again = post(f"{base}/partner/activity/append_activities", envelope(season[:1], args.signature))
    check(again["results"][0]["outcome"] == "DUPLICATE", "re-sent activity is a duplicate (idempotency)")

    blocked = activity("HARVESTED", 1, area_ha=1, quantity_qt=1)
    blocked["payload"]["plot_id"] = f"{plot}-NEW"
    blocked["idempotency_key"] = f"smoke:{run}:blocked"
    out = post(f"{base}/partner/activity/append_activities", envelope([blocked], args.signature))
    check(out["results"][0]["outcome"] == "FAILED" and out["results"][0]["error_code"] == "ACT-ERR-009",
          "harvest before sowing is blocked")

    search = post(f"{base}/dci/registry/sync/search", dci_search(
        args.signature, now, "spdci-extensions-agri:CropActivity", f"FR-SMOKE-{run}"))
    items = (search.get("message") or {}).get("search_response") or []
    records = ((items[0].get("data") or {}).get("reg_records") or []) if items else []
    check(len(records) == 6, f"DCI search returns the season's six current activities ({len(records)})")
    if records:
        check(records[0].get("crop_season", {}).get("plot_id") == plot, "DCI record renders the crop season")
        levels = (records[0].get("location") or {}).get("levels") or {}
        check((levels.get("woreda") or {}).get("code") == WOREDA and bool(levels.get("region")),
              f"DCI record carries the location by level ({levels.get('region')})")

    # The farmer's season summary is computed asynchronously by the outbox worker.
    summary = []
    for _ in range(12):
        found = post(f"{base}/dci/registry/sync/search", dci_search(
            args.signature, now, "spdci-extensions-agri:ActivityAggregate", f"FR-SMOKE-{run}"))
        items = (found.get("message") or {}).get("search_response") or []
        summary = ((items[0].get("data") or {}).get("reg_records") or []) if items else []
        if summary:
            break
        time.sleep(5)
    check(len(summary) == 1
          and summary[0].get("crop_season", {}).get("aggregate_type") == "FARMER_SEASON_SUMMARY",
          "DCI returns the farmer's season summary (aggregate)")
    if summary:
        check(summary[0].get("measures", {}).get("quantity_harvested_qt") == 15.3,
              "season summary totals the harvest (15.3 qt)")

    # The crop season's current state — what a subsidy or loan decision reads.
    found = post(f"{base}/dci/registry/sync/search", dci_search(
        args.signature, now, "spdci-extensions-agri:CropSeason", f"FR-SMOKE-{run}"))
    items = (found.get("message") or {}).get("search_response") or []
    seasons = ((items[0].get("data") or {}).get("reg_records") or []) if items else []
    check(len(seasons) == 1 and seasons[0].get("crop_season", {}).get("stage") == "HARVESTED",
          f"DCI returns the crop season's current state ({len(seasons)} season(s))")
    if seasons:
        measures = seasons[0].get("measures", {})
        check(measures.get("area_sown_ha") == 0.9 and measures.get("yield_qt_per_ha") == 17.0,
              "crop season state carries area sown and yield")

    if args.db_url:
        import psycopg

        with psycopg.connect(args.db_url) as conn:
            row = conn.execute(
                "select stage, activity_count, yield_qt_per_ha, infestation_count from "
                "g2p_activity_projection_crop_sown where plot_id = %s", (plot,)).fetchone()
            check(row is not None and row[0] == "HARVESTED" and row[1] == 6, f"projection is HARVESTED with 6 ({row})")
            deadline = time.time() + 90
            pending = None
            while time.time() < deadline:
                pending = conn.execute(
                    "select count(*) from g2p_activity_outbox o join g2p_activity_crop_sown a "
                    "on a.activity_id = o.activity_id where a.plot_id = %s and o.status <> 'PROCESSED'",
                    (plot,)).fetchone()[0]
                if pending == 0:
                    break
                time.sleep(5)
            check(pending == 0, "Celery processed every outbox event")

    print("PASSED" if not failures else f"FAILED ({len(failures)})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
