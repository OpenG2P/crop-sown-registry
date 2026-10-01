#!/usr/bin/env python3
"""Load the Crop Sown Registry's sample clusters (db-seed, LOAD_SAMPLE_DATA=true).

Inserts two approved Cluster records straight into g2p_register_clusters, as if
they had been registered and approved — the way the Farmer Registry's loader
inserts approved farmers. Idempotent: ON CONFLICT DO NOTHING on the record id.

geo_code_hierarchy_json is the woreda's ancestry read from Master Data (MD_PG*),
in the shape registry-core's G2PGeoHierarchyService produces at runtime. If
Master Data is unreachable the woreda id is still stored and the hierarchy is
left empty.

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


def load_geo_by_id() -> dict:
    """level_value_id -> (level mnemonic, name, parent id) from Master Data; {} if unavailable."""
    host, dbname = os.environ.get("MD_PGHOST"), os.environ.get("MD_PGDATABASE")
    if not host or not dbname:
        log("MD_PG* not set — clusters are stored without a geo hierarchy.")
        return {}
    try:
        conn = psycopg2.connect(
            host=host, port=os.environ.get("MD_PGPORT", "5432"), dbname=dbname,
            user=os.environ.get("MD_PGUSER", ""), password=os.environ.get("MD_PGPASSWORD", ""),
        )
    except Exception as exc:  # noqa: BLE001
        log(f"master-data unreachable ({exc}) — clusters are stored without a geo hierarchy.")
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("select level_id, level_mnemonic from g2p_geo_levels")
            mnemonic = dict(cur.fetchall())
            cur.execute("select level_value_id, level_id, level_value_mnemonic, parent_level_value_id"
                        " from g2p_geo_level_values")
            return {vid: (mnemonic.get(lid, lid), name, parent) for vid, lid, name, parent in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        log(f"could not read master-data geo ({exc}) — clusters are stored without a geo hierarchy.")
        return {}
    finally:
        conn.close()


def geo_hierarchy(woreda: str, geo_by_id: dict):
    """The woreda's ancestry, root first, or None when Master Data does not know it."""
    chain, seen, current = [], set(), woreda
    while current and current in geo_by_id and current not in seen:
        seen.add(current)
        level, name, parent = geo_by_id[current]
        chain.append({"level_mnemonic": level, "level_value_mnemonic": name, "level_value_id": current})
        current = parent
    if not chain:
        if geo_by_id:
            log(f"woreda {woreda} is not in master-data — stored without a geo hierarchy.")
        return None
    return Json({"hierarchy": list(reversed(chain))})


def search_text(cluster: dict) -> str:
    parts = [cluster["functional_record_id"], cluster["cluster_name"], cluster["crop"],
             cluster["geo_lowest_level_value_id"], cluster["coordinator_name"], cluster["coordinator_phone"]]
    return " ".join(str(p) for p in parts if p)


def main() -> None:
    geo_by_id = load_geo_by_id()
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
                    geo_hierarchy(cluster["geo_lowest_level_value_id"], geo_by_id),
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
