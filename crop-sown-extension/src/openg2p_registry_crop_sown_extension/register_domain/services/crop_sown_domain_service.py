"""Crop Sown domain rules: the crop-season context, derived values, checks, the projection
and the farmer's season summary."""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional

from openg2p_fastapi_common.context import dbengine
from openg2p_registry_core.engine import get_engines
from openg2p_registry_core.errors import G2PRegistryErrorCodes, G2PRegistryException
from openg2p_registry_core.helpers.ethiopian_calendar import ethiopian_to_gregorian
from openg2p_registry_core.services import (
    ActivityAggregateResult,
    G2PActivityDomainService,
    SampleStep,
    common_dimensions,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import crop_sown_samples

try:
    from openg2p_registry_core.helpers.master_data_client import (
        MasterDataError,
        get_master_data_client,
        master_data_read_mode,
    )
except ImportError:  # a registry-platform build from before the catalogue client: Master Data's DB

    class MasterDataError(Exception):
        pass

    def master_data_read_mode() -> str:
        return "db"

    def get_master_data_client():
        raise MasterDataError("registry-platform has no Master Data client")

_logger = logging.getLogger("crop-sown-domain-service")

# Lifecycle stages in order. Infestation and damage reports do not move a crop
# along; observations after sowing mean it is growing.
STAGE_ORDER = {"PLANNED": 1, "LAND_PREPARED": 2, "SOWN": 3, "GROWTH_OBSERVED": 4, "HARVESTED": 5}
STAGE_NAME = {"GROWTH_OBSERVED": "GROWING"}
# INFESTATION_SEVERITY codes (Master Data, ETH pack agriculture domain).
SEVERITY_ORDER = {"SEV_LOW": 1, "SEV_MEDIUM": 2, "SEV_HIGH": 3}
CONTEXT_FIELDS = ("plot_id", "crop_year", "season", "crop")

FARMER_SEASON_SUMMARY = "FARMER_SEASON_SUMMARY"

# Each season's window within the Ethiopian crop year, as Ethiopian months
# (1 Meskerem … 13 Pagume), following the CSA Agricultural Sample Survey: Meher
# crops are harvested September–February, Belg crops March–August; irrigated
# production runs through the dry season, November–May. A season without a
# window here is summarised over the whole crop year.
SEASON_WINDOWS = {
    "SEASON_MEHER": (1, 6),        # Meskerem – Yekatit
    "SEASON_BELG": (7, 13),        # Megabit – Pagume
    "SEASON_IRRIGATION": (3, 9),   # Hidar – Ginbot
}


def season_period(crop_year: int, season: str):
    """First and last day of a season in a crop year (Gregorian)."""
    first_month, last_month = SEASON_WINDOWS.get(season, (1, 13))
    start = ethiopian_to_gregorian(crop_year, first_month, 1)
    end = (
        ethiopian_to_gregorian(crop_year, last_month + 1, 1)
        if last_month < 13
        else ethiopian_to_gregorian(crop_year + 1, 1, 1)
    ) - timedelta(days=1)
    return start, end


def _num(value) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


class G2PActivityDomainServiceCropSown(G2PActivityDomainService):
    # Declarations (context fields, subject, UI hints, search fields, final
    # aggregates), the DCI record templates and the plausibility rules are
    # configuration: meta_data/activity-config/CropSown.json. The code here is
    # the context, derived values, the projection, the season summary and samples.

    # --------------------------------------------------------------- context

    def build_context(self, activity_type, subject_type, subject_id, payload):
        if not all(payload.get(field) not in (None, "") for field in CONTEXT_FIELDS):
            return None
        plot, year, season, crop = (str(payload[field]) for field in CONTEXT_FIELDS)
        return {
            "context_key": f"{plot}|{year}|{season}|{crop}",
            "context_type": "CROP_SEASON",
            "subject_type": subject_type or (self.subject_type if payload.get("farmer_id") else None),
            "subject_id": subject_id or payload.get("farmer_id"),
            "attributes": {
                "plot_id": plot,
                "crop_year": int(year) if str(year).isdigit() else year,
                "season": season,
                "crop": crop,
                "farmer_id": payload.get("farmer_id"),
                "fayda_fan": payload.get("fayda_fan"),
            },
            # The crop was changed: this season replaces that one, which is closed and linked.
            "replaces_context_id": payload.get("replaces_crop_season_id") or None,
        }

    # ---------------------------------------------------------- sample data

    async def sample_activities(self, register) -> list[SampleStep]:
        """Sample crop seasons for Master Data's sample people (see ``crop_sown_samples``).

        Asked for only when sample crop seasons are switched on, so a missing
        source is an error, not "nothing to load": the install-time samples Job
        then fails with the reason. Both must be there: Master Data's sample
        people, and the Cluster register's sample clusters (loaded by db-seed,
        which runs before the Job).
        """
        people = await _sample_people()
        if not people:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.INVALID_REQUEST.value[1],
                message="No sample people in Master Data: load its samples (masterData.geoSeed.load.samples)",
            )
        try:
            async with async_sessionmaker(dbengine.get())() as session:
                rows = (await session.execute(text(
                    "SELECT geo_lowest_level_value_id, functional_record_id, crop FROM g2p_register_clusters "
                    "WHERE record_status = 'ACTIVE' AND geo_lowest_level_value_id IS NOT NULL "
                    "AND functional_record_id NOT LIKE 'TEMP-%' ORDER BY functional_record_id"
                ))).all()
        except Exception as error:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.UNEXPECTED_ERROR.value[1],
                message=f"Could not read the Cluster register: {type(error).__name__}",
            ) from error
        # Clusters by woreda (the first by Cluster ID where a woreda has several):
        # their IDs are generated, so the samples go by where a cluster is.
        clusters: dict[str, tuple[str, str | None]] = {}
        for woreda, cluster_id, crop in rows:
            clusters.setdefault(woreda, (cluster_id, crop))
        if not clusters:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.INVALID_REQUEST.value[1],
                message="No sample clusters in the Cluster register: turn on Load Sample Data (registry.dbSeed.loadSampleData)",
            )
        return crop_sown_samples.build_steps(people, clusters)

    # ------------------------------------------------------- derived values

    def enrich_payload(self, activity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        if activity_type == "HARVESTED":
            area, quantity = _num(payload.get("area_ha")), _num(payload.get("quantity_qt"))
            if area and quantity is not None:
                payload["yield_qt_per_ha"] = round(quantity / area, 3)
        return payload

    # ------------------------------------------------------ season summary

    async def aggregate(self, session, register, activity, event_type: str) -> list[ActivityAggregateResult]:
        """The farmer's summary for the crop year and season, across all their plots and crops.

        Recomputed from the projections (current state per crop season), so a
        correction or a void is reflected, and processing an event twice is harmless.
        """
        farmer_id, crop_year, season = activity.farmer_id, activity.crop_year, activity.season
        projection = register.projection_model
        if not farmer_id or crop_year is None or not season or projection is None:
            return []
        rows = list(
            (
                await session.execute(
                    select(projection).where(
                        projection.farmer_id == farmer_id,
                        projection.crop_year == crop_year,
                        projection.season == season,
                    )
                )
            ).scalars()
        )
        return [self._season_summary(activity, farmer_id, crop_year, season, rows)]

    @staticmethod
    def _season_summary(activity, farmer_id: str, crop_year: int, season: str, rows: list) -> ActivityAggregateResult:
        def total(field: str) -> float:
            return round(sum(float(getattr(row, field) or 0) for row in rows), 4)

        by_crop: dict[str, dict[str, Any]] = {}
        for row in rows:
            crop = by_crop.setdefault(row.crop, {"plots": 0, "area_sown_ha": 0.0, "area_harvested_ha": 0.0,
                                                 "quantity_harvested_qt": 0.0})
            crop["plots"] += 1
            crop["area_sown_ha"] += float(row.area_sown_ha or 0)
            crop["area_harvested_ha"] += float(row.area_harvested_ha or 0)
            crop["quantity_harvested_qt"] += float(row.quantity_harvested_qt or 0)
        for crop in by_crop.values():
            crop["yield_qt_per_ha"] = (
                round(crop["quantity_harvested_qt"] / crop["area_harvested_ha"], 3) if crop["area_harvested_ha"] else None
            )
        harvested_area, harvested = total("area_harvested_ha"), total("quantity_harvested_qt")
        start, end = season_period(int(crop_year), season)
        return ActivityAggregateResult(
            subject_type="FARMER_ID",
            subject_id=farmer_id,
            aggregate_type=FARMER_SEASON_SUMMARY,
            period_key=f"{crop_year}|{season}",
            period_start=start,
            period_end=end,
            aggregate_value={
                "crop_seasons": len(rows),
                "plots": len({row.plot_id for row in rows}),
                "planned_area_ha": total("planned_area_ha"),
                "area_sown_ha": total("area_sown_ha"),
                "area_harvested_ha": harvested_area,
                "quantity_harvested_qt": harvested,
                "yield_qt_per_ha": round(harvested / harvested_area, 3) if harvested_area else None,
                "infestations": sum(int(row.infestation_count or 0) for row in rows),
                "damage_reports": sum(int(row.damage_count or 0) for row in rows),
                "by_crop": by_crop,
            },
            # Where the farmer's crop seasons are: the levels all their plots share
            # (e.g. one woreda, or only the zone when plots span woredas).
            geo_dimensions=common_dimensions([getattr(row, "geo_dimensions", None) for row in rows]) or {},
            custom_dimensions={"crop_year": int(crop_year), "season": season},
        )

    # ---------------------------------------------------------- projection

    def project(self, context, activities: list) -> dict[str, Any]:
        attributes = context.attributes or {}
        row: dict[str, Any] = {
            "plot_id": attributes.get("plot_id"),
            "crop_year": attributes.get("crop_year"),
            "season": attributes.get("season"),
            "crop": attributes.get("crop"),
            "farmer_id": attributes.get("farmer_id") or context.subject_id,
            "fayda_fan": attributes.get("fayda_fan"),
            "infestation_count": 0,
            "damage_count": 0,
            "pending_verification_count": 0,
        }
        stage_rank = 0
        for activity in activities:  # oldest first; later activities win
            payload = activity.payload or {}
            kind = activity.activity_type
            for field in ("farmer_id", "fayda_fan", "da_id", "variety", "cluster_id", "geo_lowest_level_value_id"):
                value = getattr(activity, field, None)
                if value:
                    row[field] = value
            if activity.verification_status == "SUBMITTED":
                row["pending_verification_count"] += 1
            rank = STAGE_ORDER.get(kind, 0)
            if rank >= stage_rank and rank:
                stage_rank = rank
                row["stage"] = STAGE_NAME.get(kind, kind)

            if kind == "PLANNED":
                row["planned_area_ha"] = activity.area_ha
                row["planned_sowing_date"] = payload.get("planned_sowing_date")
                row["expected_yield_qt_per_ha"] = payload.get("expected_yield_qt_per_ha")
            elif kind == "SOWN":
                row["area_sown_ha"] = activity.area_ha
                row["sowing_date"] = activity.occurred_at.date()
                row["seed_type"] = payload.get("seed_type")
                row["sowing_verified"] = activity.verification_status == "VERIFIED"
            elif kind == "GROWTH_OBSERVED":
                row["latest_growth_stage"] = payload.get("growth_stage")
                row["latest_crop_condition"] = payload.get("crop_condition")
            elif kind == "INFESTATION_REPORTED":
                row["infestation_count"] += 1
                severity = payload.get("severity")
                if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(row.get("max_infestation_severity"), 0):
                    row["max_infestation_severity"] = severity
            elif kind == "DAMAGE_REPORTED":
                row["damage_count"] += 1
                loss = _num(payload.get("loss_percent"))
                if loss is not None and loss > (_num(row.get("max_loss_percent")) or -1):
                    row["max_loss_percent"] = loss
            elif kind == "HARVESTED":
                row["area_harvested_ha"] = activity.area_ha
                row["quantity_harvested_qt"] = activity.quantity_qt
                row["harvest_date"] = activity.occurred_at.date()
                row["harvest_verified"] = activity.verification_status == "VERIFIED"
                area, quantity = activity.area_ha, activity.quantity_qt
                row["yield_qt_per_ha"] = (
                    round(Decimal(quantity) / Decimal(area), 3) if area and quantity is not None else None
                )
        for date_field in ("planned_sowing_date",):
            value = row.get(date_field)
            if isinstance(value, str):
                from datetime import date

                row[date_field] = date.fromisoformat(value[:10])
        return row


async def _sample_people() -> Optional[list[dict]]:
    """Master Data's sample people (individual_id, age, national_id, geo_pcode); None if unavailable.

    Read through MDS's ``/samples/get_individuals`` with the platform's Master
    Data client (master_data_read_mode = "api", the default), or from MDS's
    g2p_sample_individuals table ("db", the rollback).
    """
    if master_data_read_mode() == "api":
        try:
            people = await get_master_data_client().sample_individuals()
        except MasterDataError as error:
            _logger.info("Sample people could not be read from Master Data: %s", error)
            return None
        return [{k: p.get(k) for k in ("individual_id", "age", "national_id", "geo_pcode")} for p in people]
    engine = get_engines().get("db_engine_master_data")
    if engine is None:
        return None
    try:
        async with async_sessionmaker(engine)() as session:
            return [dict(row._mapping) for row in await session.execute(text(
                "SELECT individual_id, age, national_id, geo_pcode FROM g2p_sample_individuals"
            ))]
    except Exception:
        return None

