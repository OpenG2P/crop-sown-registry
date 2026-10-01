from typing import Optional

from openg2p_registry_core.schemas import (
    G2PGeoHistorySchema,
    G2PGeoSchema,
    G2PIntakeFormSchemaBase,
    G2PRegisterBaseSchema,
    G2PRegisterHistorySchema,
)


class G2PSchemaCluster:

    cluster_name: Optional[str] = None
    crop: Optional[str] = None
    agro_ecological_zone: Optional[str] = None
    water_source: Optional[str] = None
    cluster_area_ha: Optional[float] = None
    number_of_smallholders: Optional[int] = None
    established_year: Optional[int] = None
    coordinator_name: Optional[str] = None
    coordinator_phone: Optional[str] = None


class G2PRegisterSchemaCluster(G2PRegisterBaseSchema, G2PGeoSchema, G2PSchemaCluster):
    """
    Schema for the Cluster register.
    Inherits fields from G2PRegisterBaseSchema and G2PGeoSchema.
    Attributes inherited from G2PSchemaCluster are specific to the Cluster domain.
    """


class G2PRegisterHistorySchemaCluster(G2PRegisterHistorySchema, G2PGeoHistorySchema):
    """
    Schema for Cluster history.
    Inherits fields from G2PRegisterHistorySchema and G2PGeoHistorySchema.
    """


class G2PIntakeFormSchemaCluster(G2PIntakeFormSchemaBase, G2PRegisterBaseSchema, G2PGeoSchema, G2PSchemaCluster):
    """
    Schema for the Cluster intake form (staff registering a new cluster).
    Inherits fields from G2PRegisterBaseSchema and G2PGeoSchema.
    """
