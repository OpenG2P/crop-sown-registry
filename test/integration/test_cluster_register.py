"""The Cluster entity register: its seeded metadata, and a record round-tripping through its table."""

import importlib.util
import json
import os
import re
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from openg2p_registry_crop_sown_extension.register_domain.models import G2PRegisterCluster

pytestmark = pytest.mark.asyncio(loop_scope="session")

CLUSTER = "c5000000-0000-4000-8000-0000000c0001"
LOADER = Path(__file__).resolve().parents[2] / "docker/db-seed/load_sample_data.py"
UPGRADE = (Path(__file__).resolve().parents[2] / "crop-sown-extension/src/openg2p_registry_crop_sown_extension"
           / "meta_data/zz-upgrades/cluster_generated_id_programme_code.sql")


def _widgets(node):
    if isinstance(node, dict):
        if "widget-id" in node:
            yield node
        for value in node.values():
            yield from _widgets(value)
    elif isinstance(node, list):
        for item in node:
            yield from _widgets(item)


def _sample_loader():
    """docker/db-seed/load_sample_data.py, imported without psycopg2 (only the db-seed image has it)."""
    stub = types.ModuleType("psycopg2")
    stub.extras = types.SimpleNamespace(Json=lambda value: value)
    saved = {name: sys.modules.get(name) for name in ("psycopg2", "psycopg2.extras")}
    sys.modules.update({"psycopg2": stub, "psycopg2.extras": stub.extras})
    try:
        spec = importlib.util.spec_from_file_location("csr_load_sample_data", LOADER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _mds_client(levels, units):
    """The platform's seed MDS client (registry-platform docker/db-seed/mds_client.py,
    /seed/mds_client.py in the db-seed image) over the catalogue stand-in."""
    import httpx
    from openg2p_registry_core.testing.master_data_stub import BASE_URL, TOKEN_URL, stub_from_tables

    seed_dir = Path(os.environ.get("RP_DB_SEED_DIR", Path(__file__).resolve().parents[3] / "registry-platform/docker/db-seed"))
    if str(seed_dir) not in sys.path:
        sys.path.insert(0, str(seed_dir))
    mds_client = pytest.importorskip("mds_client", reason="registry-platform's docker/db-seed/mds_client.py not found (set RP_DB_SEED_DIR)")
    stub = stub_from_tables(levels=levels, level_values=units)

    def send(method, url, headers, body):
        response = stub._handle(httpx.Request(method, url, headers=headers, content=body or b""))
        return response.status_code, response.content

    return mds_client.MdsClient(BASE_URL, token_url=TOKEN_URL, client_id="registry-staff-portal",
                                client_secret="secret", transport=send)


async def test_cluster_register_is_seeded(database):
    async with database.connect() as conn:
        definition = (await conn.execute(text(
            "SELECT register_mnemonic, register_subject, register_purpose, register_rank, "
            "functional_id_generation_required, dedup_is_enabled, completion_score_required, "
            "requires_registrant_authentication FROM g2p_register_definitions WHERE register_id = :r"),
            {"r": CLUSTER})).one()
        # The Cluster ID is generated (functional_id_generation_required).
        assert tuple(definition) == ("Cluster", "Clusters", "REGISTER", 2, True, False, False, False)

        schema = (await conn.execute(text(
            "SELECT search_result_schema, filter_schema FROM g2p_register_schemas WHERE register_id = :r"),
            {"r": CLUSTER})).one()
        assert [(f["field_name"], f["display_label"]) for f in schema.search_result_schema[:2]] == [
            ("functional_record_id", "Cluster ID"), ("programme_cluster_code", "Programme Cluster Code")]
        assert "programme_cluster_code" in {f["field_name"] for f in schema.filter_schema}

        sections = (await conn.execute(text(
            "SELECT s.section_id, s.section_register_id, s.section_ui_schema, s.cr_auto_approve_for_staff_portal "
            "FROM g2p_register_ui_tab_sections ts JOIN g2p_register_sections s ON s.section_id = ts.section_id "
            "JOIN g2p_register_ui_tabs t ON t.tab_id = ts.tab_id "
            "WHERE t.register_id = :r ORDER BY ts.section_order"), {"r": CLUSTER})).all()
        assert [s.section_id for s in sections] == ["cluster_cluster_details_section_01",
                                                    "cluster_location_resources_section_02"]
        assert all(s.section_register_id == CLUSTER and not s.cr_auto_approve_for_staff_portal for s in sections)

        # Every widget writes a real Cluster column, and every dropdown names a Master Data list.
        columns = set(G2PRegisterCluster.__table__.columns.keys())
        attributes = set((await conn.execute(text("SELECT attribute_id FROM g2p_attributes"))).scalars())
        bound = {}
        for section in sections:
            for widget in _widgets(section.section_ui_schema):
                paths = widget["widget-data-path"]
                for path in paths.values() if isinstance(paths, dict) else [paths]:
                    register_id, field = path.split(".", 1)
                    assert register_id == CLUSTER and field in columns, path
                    bound[field] = widget
        assert {"functional_record_id", "programme_cluster_code", "cluster_name", "crop", "established_year", "coordinator_name",
                "coordinator_phone", "geo_lowest_level_value_id", "cluster_area_ha", "number_of_smallholders",
                "agro_ecological_zone", "water_source"} <= set(bound)
        assert bound["geo_lowest_level_value_id"]["widget"] == "geo-hierarchy"
        # Staff never type the Cluster ID: it is shown, read-only, once generated.
        assert bound["functional_record_id"]["widget-readonly"] and not bound["functional_record_id"]["widget-required"]
        assert bound["programme_cluster_code"]["widget-label"] == "Programme Cluster Code"
        assert not bound["programme_cluster_code"]["widget-required"]
        for field, attribute in (("crop", "CROP_COMMODITY"), ("agro_ecological_zone", "AGRO_ECOLOGICAL_ZONE"),
                                 ("water_source", "WATER_SOURCE")):
            assert bound[field]["widget-data-source"]["params"]["attribute_id"] == attribute
            assert attribute in attributes

        intake = (await conn.execute(text(
            "SELECT f.used_only_in_ingestion_pipeline, count(ts.section_id) FROM g2p_intake_form_definitions f "
            "JOIN g2p_intake_form_ui_tabs t ON t.form_id = f.form_id "
            "JOIN g2p_intake_form_ui_tab_sections ts ON ts.tab_id = t.tab_id "
            "WHERE f.register_id = :r GROUP BY f.used_only_in_ingestion_pipeline"), {"r": CLUSTER})).one()
        assert tuple(intake) == (False, 2)

        policies = (await conn.execute(text(
            "SELECT policy_scope, policy_key FROM g2p_registry_awe_policy_configurations WHERE register_id = :r "
            "ORDER BY policy_scope"), {"r": CLUSTER})).all()
        assert [tuple(p) for p in policies] == [("INTAKE_FORM", "registry.intake_form.cluster"),
                                                ("REGISTER", "registry.change_request.cluster")]


async def test_cluster_record_round_trips(database):
    sessions = async_sessionmaker(database, expire_on_commit=False)
    try:
        async with sessions() as session:
            session.add(G2PRegisterCluster(
                functional_record_id="CL-TEST-001", programme_cluster_code="CL-ET0406-099",
                cluster_name="Test teff cluster", crop="CROP_TEFF",
                agro_ecological_zone="AEZ_WEYNA_DEGA", water_source="WS_RAINFED", cluster_area_ha=120,
                number_of_smallholders=85, established_year=2016, coordinator_name="Tadesse Bekele",
                coordinator_phone="+251911000101", geo_lowest_level_value_id="ET040611",
                created_by="test", created_at=datetime(2026, 9, 26), last_approved_at=datetime(2026, 9, 26),
                last_approved_by="test",
            ))
            await session.commit()
        async with sessions() as session:
            cluster = (await session.execute(
                select(G2PRegisterCluster).where(G2PRegisterCluster.functional_record_id == "CL-TEST-001"))).scalar_one()
        assert cluster.record_name == "Test teff cluster"  # record_name = cluster name
        assert {"CL-TEST-001", "CL-ET0406-099", "CROP_TEFF", "ET040611"} <= set(cluster.search_text.split())
        assert (cluster.crop, cluster.geo_lowest_level_value_id, float(cluster.cluster_area_ha),
                cluster.number_of_smallholders, cluster.established_year, cluster.record_status) == (
            "CROP_TEFF", "ET040611", 120.0, 85, 2016, "ACTIVE")
    finally:
        async with database.begin() as conn:
            await conn.execute(text("DELETE FROM g2p_register_clusters WHERE functional_record_id = 'CL-TEST-001'"))


async def test_sample_clusters_use_master_data_codes_and_woredas(database):
    loader = _sample_loader()
    async with database.connect() as conn:
        codes = {(a, v) for a, v in (await conn.execute(
            text("SELECT attribute_id, value_id FROM g2p_attribute_values"))).all()}
        levels = [dict(r._mapping) for r in (await conn.execute(text(
            "SELECT level_id, level_mnemonic, parent_level_id FROM g2p_geo_levels")))]
        units = [dict(r._mapping) for r in (await conn.execute(text(
            "SELECT level_value_id, level_id, level_value_mnemonic, parent_level_value_id "
            "FROM g2p_geo_level_values")))]

    # Fixed IDs in the generator's shape (pool "cluster": CL- and ten digits), as the Farmer
    # Registry seeds fixed farmer IDs; the programme's codes are programme_cluster_code.
    assert all(re.fullmatch(r"CL-[1-9][0-9]{9}", c["functional_record_id"]) for c in loader.CLUSTERS)
    assert [c["programme_cluster_code"] for c in loader.CLUSTERS] == ["CL-ET0406-001", "CL-ET0101-001"]
    assert {c["programme_cluster_code"] for c in loader.CLUSTERS} <= set(loader.search_text(loader.CLUSTERS[0]).split()
                                                                         + loader.search_text(loader.CLUSTERS[1]).split())
    for cluster in loader.CLUSTERS:
        for field, attribute in (("crop", "CROP_COMMODITY"), ("agro_ecological_zone", "AGRO_ECOLOGICAL_ZONE"),
                                 ("water_source", "WATER_SOURCE")):
            assert (attribute, cluster[field]) in codes, (cluster["functional_record_id"], field)
        assert set(loader.FIELDS) <= set(G2PRegisterCluster.__table__.columns.keys())

    # The loader reads the geography through Master Data's API, never its database:
    # serve the pack's geography from the platform's catalogue stand-in.
    hierarchy = loader.geo_hierarchy("ET040611", _mds_client(levels, units))["hierarchy"]
    assert [(h["level_mnemonic"], h["level_value_id"]) for h in hierarchy] == [
        ("country", "ET"), ("region", "ET04"), ("zone", "ET0406"), ("woreda", "ET040611")]
    assert hierarchy[-1]["level_value_mnemonic"] == "Sheno town"


async def test_upgrade_moves_typed_codes_to_programme_cluster_code(database):
    """An install from before generated Cluster IDs: no programme_cluster_code column, the old
    metadata, and clusters whose functional_record_id is the typed programme code."""
    original = {}
    async with database.connect() as conn:
        for table, key in (("g2p_register_definitions", "register_id"), ("g2p_register_schemas", "register_id")):
            original[table] = dict((await conn.execute(
                text(f"SELECT * FROM {table} WHERE {key} = :r"), {"r": CLUSTER})).one()._mapping)
        original["section"] = (await conn.execute(text(
            "SELECT section_ui_schema FROM g2p_register_sections "
            "WHERE section_id = 'cluster_cluster_details_section_01'"))).scalar()
    old_panel = {"widgets": [
        {"widget": "text", "widget-id": "functional_record_id", "widget-type": "input", "widget-label": "Cluster code",
         "widget-readonly": False, "widget-required": True,
         "widget-data-path": f"{CLUSTER}.functional_record_id"}],
        "panel-id": "panel_cluster_identity", "panel-orientation": "vertical"}
    old_schema = original["g2p_register_schemas"]["search_result_schema"]
    old_schema = [{**f, "display_label": "Cluster Code"} if f["field_name"] == "functional_record_id" else f
                  for f in old_schema if f["field_name"] != "programme_cluster_code"]
    rows = ["CL-ET0406-001", "CL-4729318560", "CL-ET0101-001"]
    try:
        async with database.begin() as conn:
            for table in ("g2p_register_clusters", "g2p_register_history_clusters", "g2p_intake_form_clusters"):
                await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN programme_cluster_code"))
            await conn.execute(text(
                "UPDATE g2p_register_definitions SET functional_id_generation_required = FALSE WHERE register_id = :r"),
                {"r": CLUSTER})
            await conn.execute(text(
                "UPDATE g2p_register_schemas SET search_result_schema = CAST(:s AS json) WHERE register_id = :r"),
                {"s": json.dumps(old_schema), "r": CLUSTER})
            await conn.execute(text(
                "UPDATE g2p_register_sections SET section_ui_schema = jsonb_set(section_ui_schema, "
                "'{panels,0,panels,0}', CAST(:p AS jsonb)) WHERE section_id = 'cluster_cluster_details_section_01'"),
                {"p": json.dumps(old_panel)})
            for n, code in enumerate(rows):
                await conn.execute(text(
                    "INSERT INTO g2p_register_clusters (internal_record_id, functional_record_id, cluster_name, "
                    "record_status, created_by, created_at, last_approved_at, last_approved_by) VALUES "
                    "(:i, :f, :f, 'ACTIVE', 'test', now(), now(), 'test')"),
                    {"i": f"c5000000-0000-4000-8000-0000000c90{n:02d}", "f": code})

        async with database.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection  # asyncpg: multi-statement like psql
            sql = UPGRADE.read_text()
            await raw.execute(sql)
            # Again with a programme code already set on one cluster: the copy fills only blanks.
            await conn.execute(text("UPDATE g2p_register_clusters SET programme_cluster_code = NULL"))
            await conn.execute(text("UPDATE g2p_register_clusters SET programme_cluster_code = 'KEEP-ME' "
                                    "WHERE functional_record_id = 'CL-ET0101-001'"))
            await raw.execute(sql)
            await raw.execute(sql)  # idempotent

        async with database.connect() as conn:
            codes = dict((await conn.execute(text(
                "SELECT functional_record_id, programme_cluster_code FROM g2p_register_clusters"))).all())
            assert codes == {"CL-ET0406-001": "CL-ET0406-001",  # typed code copied; the ID itself unchanged
                             "CL-4729318560": None,              # a generated ID is not a programme code
                             "CL-ET0101-001": "KEEP-ME"}         # an existing value is not overwritten
            for table in ("g2p_register_history_clusters", "g2p_intake_form_clusters"):
                assert (await conn.execute(text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_name = :t "
                    "AND column_name = 'programme_cluster_code'"), {"t": table})).scalar() == 1
            assert (await conn.execute(text(
                "SELECT functional_id_generation_required FROM g2p_register_definitions WHERE register_id = :r"),
                {"r": CLUSTER})).scalar() is True
            schema = (await conn.execute(text(
                "SELECT search_result_schema FROM g2p_register_schemas WHERE register_id = :r"), {"r": CLUSTER})).scalar()
            assert schema == original["g2p_register_schemas"]["search_result_schema"]
            section = (await conn.execute(text(
                "SELECT section_ui_schema FROM g2p_register_sections "
                "WHERE section_id = 'cluster_cluster_details_section_01'"))).scalar()
            assert section == original["section"]  # the same metadata a fresh install gets
    finally:
        async with database.begin() as conn:
            await conn.execute(text("DELETE FROM g2p_register_clusters WHERE functional_record_id = ANY(:ids)"),
                               {"ids": list(rows)})
