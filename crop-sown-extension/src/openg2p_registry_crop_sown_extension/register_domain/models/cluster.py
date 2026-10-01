"""The Cluster register: farmer clusters under a government cluster programme.

A cluster is a group of smallholders farming one crop together in a woreda. It
is a conventional (entity) register maintained through change requests approved
in AWE — unlike CropSown, which is an append-only activity register.

The cluster code (e.g. ``CL-ET0406-001``) is the record's functional_record_id,
entered by staff: this registry runs without the ID generator. The record name
is the cluster name. Crop, agro-ecological zone and water source are Master Data
codes (CROP_COMMODITY, AGRO_ECOLOGICAL_ZONE, WATER_SOURCE); the location is the
woreda, held in G2PGeo's geo_lowest_level_value_id.
"""

from openg2p_registry_core.models import G2PGeo, G2PGeoHistory, G2PRegister, G2PRegisterHistory
from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..services import G2PRegisterDomainServiceCluster


class G2PCluster:

    cluster_name: Mapped[str] = mapped_column(String, nullable=True)
    crop: Mapped[str] = mapped_column(String, nullable=True, index=True)  # CROP_COMMODITY (Master Data)
    agro_ecological_zone: Mapped[str] = mapped_column(String, nullable=True)  # AGRO_ECOLOGICAL_ZONE (Master Data)
    water_source: Mapped[str] = mapped_column(String, nullable=True)  # WATER_SOURCE (Master Data)
    cluster_area_ha: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    number_of_smallholders: Mapped[int] = mapped_column(Integer, nullable=True)
    established_year: Mapped[int] = mapped_column(Integer, nullable=True)  # Ethiopian calendar year, e.g. 2016
    coordinator_name: Mapped[str] = mapped_column(String, nullable=True)
    coordinator_phone: Mapped[str] = mapped_column(String, nullable=True)


# All Register classes should have the prefix G2PRegister
class G2PRegisterCluster(G2PRegister, G2PGeo, G2PCluster):
    __tablename__ = "g2p_register_clusters"

    def get_search_text_fields(self) -> str:
        """Return cluster fields used to build search_text."""
        return G2PRegisterDomainServiceCluster().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        """Return cluster record_name from domain service implementation."""
        return G2PRegisterDomainServiceCluster().construct_record_name(self.to_dict())


# All Register History classes should have the prefix G2PRegisterHistory
class G2PRegisterHistoryCluster(G2PRegisterHistory, G2PGeoHistory, G2PCluster):
    __tablename__ = "g2p_register_history_clusters"


# All Intake Form classes should have the prefix G2PIntakeForm
class G2PIntakeFormCluster(G2PIntakeForm, G2PRegister, G2PGeo, G2PCluster):
    __tablename__ = "g2p_intake_form_clusters"

    def get_search_text_fields(self) -> str:
        """Return cluster fields used to build search_text."""
        return G2PRegisterDomainServiceCluster().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        """Return cluster record_name from domain service implementation."""
        return G2PRegisterDomainServiceCluster().construct_record_name(self.to_dict())
