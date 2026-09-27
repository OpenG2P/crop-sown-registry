"""Crop Sown domain rules: the crop-season context, derived values, checks and the projection."""

from decimal import Decimal
from typing import Any, Optional

from openg2p_registry_core.services import G2PActivityDomainService

# Lifecycle stages in order. Infestation and damage reports do not move a crop
# along; observations after sowing mean it is growing.
STAGE_ORDER = {"PLANNED": 1, "LAND_PREPARED": 2, "SOWN": 3, "GROWTH_OBSERVED": 4, "HARVESTED": 5}
STAGE_NAME = {"GROWTH_OBSERVED": "GROWING"}
SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
CONTEXT_FIELDS = ("plot_id", "crop_year", "season", "crop")


def _num(value) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


class G2PActivityDomainServiceCropSown(G2PActivityDomainService):
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
        }

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
