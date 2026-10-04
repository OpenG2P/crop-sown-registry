"""Crop Sown domain rules: the crop-season context, derived values, checks, the projection
and the farmer's season summary."""

from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional

import logging

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
    # A crop season is one crop on one plot in one season, for one farmer: a
    # correction can't move an activity to another one (void and record anew).
    context_fields = ("farmer_id", *CONTEXT_FIELDS)
    ui_hints = {
        "summary_fields": ["farmer_id", "plot_id", "crop", "area_ha", "quantity_qt"],
        "context_columns": ["farmer_id", "plot_id", "crop_year", "season", "crop", "stage",
                            "area_sown_ha", "yield_qt_per_ha"],
        # A batch is usually one season's entries by one development agent.
        "batch_carry_fields": ["crop_year", "season", "da_id"],
        "search_placeholder": "Search farmer, plot, crop…",
        "context_search_placeholder": "Search by key (plot, season, crop…)",
    }
    # A farmer's season summary is final once the season's window is locked
    # (for all activity types) and its activities are processed. Plans are often
    # made before the window, so lock from the planning start to keep it final.
    final_on_period_lock = (FARMER_SEASON_SUMMARY,)
    # A partner's consent may name the farmer by Fayda FAN while the search is by
    # farmer ID: allowed when this registry's own records link the two.
    subject_id_fields = ("fayda_fan",)

    # --------------------------------------------------------------- context

    def build_context(self, activity_type, subject_type, subject_id, payload):
        if not all(payload.get(field) not in (None, "") for field in CONTEXT_FIELDS):
            return None
        plot, year, season, crop = (str(payload[field]) for field in CONTEXT_FIELDS)
        return {
            "context_key": f"{plot}|{year}|{season}|{crop}",
            "context_type": "CROP_SEASON",
            "subject_type": subject_type or ("FARMER_ID" if payload.get("farmer_id") else None),
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

    def search_text_values(self, activity_type: str, payload: dict[str, Any]) -> list[str]:
        return [str(payload[field]) for field in ("farmer_id", "fayda_fan", "plot_id", "crop", "cluster_id")
                if payload.get(field)]

    # ------------------------------------------------------------- checks

    def validate(self, activity_type: str, payload: dict[str, Any], context_activities: list) -> list[str]:
        """Plausibility warnings against what the context already holds (never blocking)."""
        warnings: list[str] = []
        latest = {}
        for activity in context_activities:
            latest[activity.activity_type] = activity
        planned, sown = latest.get("PLANNED"), latest.get("SOWN")
        area = _num(payload.get("area_ha"))

        if activity_type == "SOWN" and planned is not None and area and planned.area_ha:
            if area > float(planned.area_ha) * 1.5:
                warnings.append(f"Area sown {area} ha is more than 1.5 × the planned {float(planned.area_ha)} ha")
        if activity_type in ("GROWTH_OBSERVED", "HARVESTED", "INFESTATION_REPORTED", "DAMAGE_REPORTED"):
            if sown is not None and area and sown.area_ha and area > float(sown.area_ha) + 1e-9:
                warnings.append(f"Area {area} ha exceeds the {float(sown.area_ha)} ha sown")
        if activity_type == "HARVESTED":
            yield_per_ha = _num(payload.get("yield_qt_per_ha"))
            if yield_per_ha is not None and yield_per_ha > 150:
                warnings.append(f"Yield of {yield_per_ha} qt/ha is implausibly high; check quantity and area")
            disposed = sum(_num(payload.get(f)) or 0 for f in ("stored_qt", "sold_qt", "consumed_qt", "seed_reserved_qt"))
            quantity = _num(payload.get("quantity_qt")) or 0
            loss = _num(payload.get("post_harvest_loss_qt")) or 0
            if disposed > quantity - loss + 1e-6:
                warnings.append("Stored, sold, consumed and seed quantities add up to more than was harvested")
        return warnings

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

    # ------------------------------------------------------------- sharing
    #
    # DCI records for a crop season's current state (reg_record_type
    # spdci-extensions-agri:CropSeason) and for aggregates (...:ActivityAggregate),
    # keyed by farmer ID. Top-level keys are this registry's consent scopes —
    # farmer_reference, crop_season, measures, location — the same as for
    # activities, so a partner's policy covers all three record types.

    def dci_state_record(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "@type": "spdci-extensions-agri:CropSeason",
            "farmer_reference": {"farmer_id": state.get("farmer_id"), "fayda_fan": state.get("fayda_fan")},
            "crop_season": {
                "crop_season_id": state.get("context_id"),
                "plot_id": state.get("plot_id"),
                "crop_year": state.get("crop_year"),
                "season": state.get("season"),
                "crop": state.get("crop"),
                "variety": state.get("variety"),
                "stage": state.get("stage"),
                "status": state.get("context_status"),
                "last_activity_type": state.get("last_activity_type"),
                "last_occurred_at": state.get("last_occurred_at"),
                # The crop was changed: the season this one replaced, or was replaced by.
                "replaces_crop_season_id": state.get("replaces_context_id"),
                "replaced_by_crop_season_id": state.get("replaced_by_context_id"),
            },
            "measures": {key: state.get(key) for key in (
                "planned_area_ha", "planned_sowing_date", "expected_yield_qt_per_ha",
                "area_sown_ha", "sowing_date", "seed_type", "sowing_verified", "harvest_verified",
                "latest_growth_stage", "latest_crop_condition",
                "infestation_count", "max_infestation_severity", "damage_count", "max_loss_percent",
                "area_harvested_ha", "quantity_harvested_qt", "yield_qt_per_ha", "harvest_date",
                "pending_verification_count",
            )},
            "location": state.get("geo_dimensions"),
        }

    def dci_aggregate_record(self, aggregate: dict[str, Any]) -> dict[str, Any]:
        custom = aggregate.get("custom_dimensions") or {}
        return {
            "@type": "spdci-extensions-agri:ActivityAggregate",
            "farmer_reference": {"farmer_id": aggregate.get("subject_id")},
            "crop_season": {
                "aggregate_type": aggregate.get("aggregate_type"),
                "period_key": aggregate.get("period_key"),
                "crop_year": custom.get("crop_year"),
                "season": custom.get("season"),
                "period_start": aggregate.get("period_start"),
                "period_end": aggregate.get("period_end"),
                "computed_at": aggregate.get("computed_at"),
                # Final once the season is closed: the figure a subsidy or payment can rely on.
                "is_final": bool(aggregate.get("is_final")),
                "finalised_at": aggregate.get("finalised_at"),
            },
            "measures": aggregate.get("aggregate_value"),
            "location": aggregate.get("geo_dimensions") or None,
        }

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
