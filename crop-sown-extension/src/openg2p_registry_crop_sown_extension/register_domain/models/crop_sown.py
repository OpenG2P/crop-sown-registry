"""The Crop Sown activity register and its current-state projection.

One activity context is one crop on one plot in one season:
``<plot_id>|<crop_year>|<season>|<crop>``. Intercropping is two contexts on the
same plot. Every stage — planned, land prepared, sown, observed, infested,
damaged, harvested — is an append-only activity in that context.

The columns below are promoted from the payload so they can be filtered,
indexed, used by data policies and indicators. Everything else a stage records
stays in the JSONB ``payload``, validated by the activity type's JSON Schema.
"""

from datetime import date

from openg2p_registry_core.models import G2PActivity, G2PActivityProjection, G2PGeo
from sqlalchemy import Boolean, Date, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column


class G2PActivityCropSown(G2PActivity, G2PGeo):
    __tablename__ = "g2p_activity_crop_sown"
    __table_args__ = {"extend_existing": True}

    # Who and where (references into other registries; checked leniently)
    farmer_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    fayda_fan: Mapped[str] = mapped_column(String, nullable=True, index=True)
    plot_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    da_id: Mapped[str] = mapped_column(String, nullable=True, index=True)

    # The season and crop the context is about
    crop_year: Mapped[int] = mapped_column(Integer, nullable=True, index=True)  # Ethiopian year, e.g. 2019
    season: Mapped[str] = mapped_column(String, nullable=True, index=True)  # CROP_SEASON (Master Data)
    crop: Mapped[str] = mapped_column(String, nullable=True, index=True)  # CROP_COMMODITY (Master Data)
    variety: Mapped[str] = mapped_column(String, nullable=True)  # SEED_VARIETY (Master Data)

    # Measures most stages carry
    area_ha: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    quantity_qt: Mapped[float] = mapped_column(Numeric(14, 3), nullable=True)

    cluster_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    photo_document_id: Mapped[str] = mapped_column(String, nullable=True)

    def get_search_text_fields(self) -> list[str]:
        return [self.farmer_id or "", self.fayda_fan or "", self.plot_id or "", self.crop or ""]


class G2PActivityProjectionCropSown(G2PActivityProjection):
    """Crop season status: where one crop on one plot stands this season."""

    __tablename__ = "g2p_activity_projection_crop_sown"
    __table_args__ = {"extend_existing": True}

    farmer_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    fayda_fan: Mapped[str] = mapped_column(String, nullable=True)
    plot_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    da_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    crop_year: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    season: Mapped[str] = mapped_column(String, nullable=True, index=True)
    crop: Mapped[str] = mapped_column(String, nullable=True, index=True)
    variety: Mapped[str] = mapped_column(String, nullable=True)
    cluster_id: Mapped[str] = mapped_column(String, nullable=True)
    geo_lowest_level_value_id: Mapped[str] = mapped_column(String, nullable=True, index=True)

    # Furthest lifecycle stage reached: PLANNED → LAND_PREPARED → SOWN → GROWING → HARVESTED
    stage: Mapped[str] = mapped_column(String, nullable=True, index=True)
    planned_area_ha: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    planned_sowing_date: Mapped[date] = mapped_column(Date, nullable=True)
    expected_yield_qt_per_ha: Mapped[float] = mapped_column(Numeric(10, 3), nullable=True)
    area_sown_ha: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    sowing_date: Mapped[date] = mapped_column(Date, nullable=True)
    seed_type: Mapped[str] = mapped_column(String, nullable=True)
    sowing_verified: Mapped[bool] = mapped_column(Boolean, nullable=True)
    latest_growth_stage: Mapped[str] = mapped_column(String, nullable=True)
    latest_crop_condition: Mapped[str] = mapped_column(String, nullable=True)
    infestation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_infestation_severity: Mapped[str] = mapped_column(String, nullable=True)
    damage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_loss_percent: Mapped[float] = mapped_column(Numeric(6, 2), nullable=True)
    area_harvested_ha: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    quantity_harvested_qt: Mapped[float] = mapped_column(Numeric(14, 3), nullable=True)
    yield_qt_per_ha: Mapped[float] = mapped_column(Numeric(10, 3), nullable=True)
    harvest_date: Mapped[date] = mapped_column(Date, nullable=True)
    pending_verification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
