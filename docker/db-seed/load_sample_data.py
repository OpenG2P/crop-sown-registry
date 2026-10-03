#!/usr/bin/env python3
"""Load the Crop Sown Registry's sample clusters (db-seed, LOAD_SAMPLE_DATA=true).

Inserts two approved Cluster records straight into g2p_register_clusters, as if
they had been registered and approved — the way the Farmer Registry's loader
inserts approved farmers. Idempotent: ON CONFLICT DO NOTHING on the record id.

geo_code_hierarchy_json is the woreda's ancestry read from Master Data through
its API (/catalogue/get_geo_unit with its ancestors, via the platform's
/seed/mds_client.py and the MDS_* env the chart passes), in the shape
registry-core's G2PGeoHierarchyService produces at runtime. Master Data's
database is never read. If Master Data is unreachable the woreda id is still
stored and the hierarchy is left empty.

Sample crop-season activities are not loaded here: they go through the activity
APIs (the platform's sample task), not straight into tables.
"""

import os
import sys

import psycopg2
from psycopg2.extras import Json

SEEDER = "seeder"
CREATED_AT = "2026-09-26 00:00:00"

CLUSTERS = [
    {
        "internal_record_id": "c5000000-0000-4000-8000-0000000c1001",
        "functional_record_id": "CL-ET0406-001",
        "cluster_name": "Sheno teff cluster",
        "crop": "CROP_TEFF",
        "geo_lowest_level_value_id": "ET040611",  # Sheno town, North Shewa (OR), Oromia
        "agro_ecological_zone": "AEZ_WEYNA_DEGA",
        "water_source": "WS_RAINFED",
        "cluster_area_ha": 120,
        "number_of_smallholders": 85,
        "established_year": 2016,
        "coordinator_name": "Tadesse Bekele",
        "coordinator_phone": "+251911000101",
    },
    {
        "internal_record_id": "c5000000-0000-4000-8000-0000000c1002",
        "functional_record_id": "CL-ET0101-001",
        "cluster_name": "Tahtay Adiyabo wheat cluster",
        "crop": "CROP_WHEAT",
        "geo_lowest_level_value_id": "ET010101",  # Tahtay Adiyabo, Tigray
        "agro_ecological_zone": "AEZ_KOLLA",
        "water_source": "WS_IRRIGATION_SURFACE",
        "cluster_area_ha": 80,
        "number_of_smallholders": 40,
        "established_year": 2017,
        "coordinator_name": "Hagos Gebremedhin",
        "coordinator_phone": "+251914000202",
    },
]

FIELDS = [
    "cluster_name", "crop", "agro_ecological_zone", "water_source", "cluster_area_ha",
    "number_of_smallholders", "established_year", "coordinator_name", "coordinator_phone",
]


def log(message: str) -> None:
    print(f"[load-sample-data] {message}", flush=True)


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"[load-sample-data] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def master_data():
    """The platform's Master Data API client, or None (logged) when unavailable."""
    try:
        from mds_client import MdsClient  # /seed/mds_client.py, from the RP db-seed base image
    except ImportError:
        log("mds_client.py is not in this image — clusters are stored without a geo hierarchy.")
        return None
    client = MdsClient.from_env()
    if client is None:
        log("MDS_API_URL not set — clusters are stored without a geo hierarchy.")
    return client


def geo_hierarchy(woreda: str, client):
    """The woreda's ancestry, root first, or None when Master Data does not know it."""
    if client is None:
        return None
    from mds_client import MdsError

    try:
        hierarchy = client.geo_hierarchy_json(woreda)
    except MdsError as exc:
        log(f"could not read woreda {woreda} from master-data ({exc}) — stored without a geo hierarchy.")
        return None
    if not hierarchy:
        log(f"woreda {woreda} is not in master-data — stored without a geo hierarchy.")
        return None
    return Json(hierarchy)


def search_text(cluster: dict) -> str:
    parts = [cluster["functional_record_id"], cluster["cluster_name"], cluster["crop"],
             cluster["geo_lowest_level_value_id"], cluster["coordinator_name"], cluster["coordinator_phone"]]
    return " ".join(str(p) for p in parts if p)


def main() -> None:
    mds = master_data()
    columns = [
        "internal_record_id", "functional_record_id", "record_name",
        "created_by", "created_at", "last_approved_at", "last_approved_by",
        "search_text", "record_status", "geo_lowest_level_value_id", "geo_code_hierarchy_json", *FIELDS,
    ]
    sql = (
        'INSERT INTO "public"."g2p_register_clusters" ('
        + ", ".join(f'"{c}"' for c in columns)
        + ") VALUES (" + ", ".join(["%s"] * len(columns)) + ')'
        + ' ON CONFLICT DO NOTHING'
    )

    conn = psycopg2.connect(
        host=env("PGHOST"), port=os.environ.get("PGPORT", "5432"), dbname=env("PGDATABASE"),
        user=env("PGUSER"), password=env("PGPASSWORD"),
    )
    try:
        with conn, conn.cursor() as cur:
            inserted = 0
            for cluster in CLUSTERS:
                cur.execute(sql, [
                    cluster["internal_record_id"], cluster["functional_record_id"], cluster["cluster_name"],
                    SEEDER, CREATED_AT, CREATED_AT, SEEDER,
                    search_text(cluster), "ACTIVE", cluster["geo_lowest_level_value_id"],
                    geo_hierarchy(cluster["geo_lowest_level_value_id"], mds),
                    *(cluster[f] for f in FIELDS),
                ])
                inserted += cur.rowcount
        log(f"  -> g2p_register_clusters: {inserted} inserted, {len(CLUSTERS) - inserted} already present")
        log("Done.")
    except Exception as exc:
        print(f"[load-sample-data] FAILED: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
