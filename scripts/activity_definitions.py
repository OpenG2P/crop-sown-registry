"""The Crop Sown Registry's configuration, in one readable place.

`scripts/build_seed_sql.py` turns this into the seed SQL under
crop-sown-extension/.../meta_data/. Edit here, regenerate, commit both.

Fields follow the crop-sown sample registry, extended with items from the FAO
World Programme for the Census of Agriculture 2020 crop module and Ethiopia's
CSA Agricultural Sample Survey (Meher/Belg seasons, UREA/DAP/NPS fertilisers,
quintals).

Every coded field names a Master Data code list, read live from Master Data
(the ETH country pack's agriculture domain, openg2p-data
packs/ETH/domains/agriculture). This registry keeps no code lists of its own.
"""

REGISTER_ID = "c5000000-0000-4000-8000-000000000001"
REGISTER_MNEMONIC = "CropSown"

# Payload fields named like these are promoted to typed columns on
# g2p_activity_crop_sown (see models/crop_sown.py).
_CONTEXT = {
    "farmer_id": {"type": "string", "title": "Farmer ID (Farmer Registry)", "minLength": 3},
    "fayda_fan": {"type": "string", "title": "Fayda FAN", "pattern": "^[0-9]{12,16}$"},
    "plot_id": {"type": "string", "title": "Plot (Farmer Registry land record)", "minLength": 3},
    "crop_year": {"type": "integer", "title": "Crop year (Ethiopian calendar)", "minimum": 2000, "maximum": 2100},
    "season": {"type": "string", "title": "Season"},
    "crop": {"type": "string", "title": "Crop"},
    "crop_other": {"type": "string", "title": "Crop (if other)"},
    "da_id": {"type": "string", "title": "Development agent ID"},
    "latitude": {"type": "string", "title": "Latitude"},
    "longitude": {"type": "string", "title": "Longitude"},
    "geo_lowest_level_value_id": {"type": "string", "title": "Woreda (where the plot is)"},
    "remarks": {"type": "string", "title": "Remarks", "maxLength": 2000},
    # When the crop on a plot is changed for the season, the new crop season
    # names the one it replaces; that one is closed and points to the new one.
    "replaces_crop_season_id": {"type": "string", "title": "Replaces crop season (if the crop was changed)"},
}
_CONTEXT_REQUIRED = ["farmer_id", "plot_id", "crop_year", "season", "crop"]

_AREA = {"type": "number", "exclusiveMinimum": 0, "maximum": 10000}
_QT = {"type": "number", "minimum": 0, "maximum": 1000000}
_KG = {"type": "number", "minimum": 0, "maximum": 1000000}
_PCT = {"type": "number", "minimum": 0, "maximum": 100}
_DATE = {"type": "string", "format": "date"}

_FERTILIZER_LIST = {
    "type": "array",
    "title": "Fertilisers applied",
    "items": {
        "type": "object",
        "required": ["fertilizer_type", "quantity_kg"],
        "properties": {
            "fertilizer_type": {"type": "string", "title": "Type"},
            "quantity_kg": {**_KG, "title": "Quantity (kg)"},
        },
    },
}


def _schema(required: list[str], properties: dict) -> dict:
    return {
        "type": "object",
        "required": _CONTEXT_REQUIRED + required,
        "properties": {**_CONTEXT, **properties},
        "additionalProperties": False,
    }


_REFERENCES = {
    "crop": {"kind": "ATTRIBUTE", "attribute": "CROP_COMMODITY", "mode": "STRICT"},
    "season": {"kind": "ATTRIBUTE", "attribute": "CROP_SEASON", "mode": "STRICT"},
    "variety": {"kind": "ATTRIBUTE", "attribute": "SEED_VARIETY", "mode": "LENIENT"},
    # Identifiers held by other registries: format only, never blocking.
    "farmer_id": {"kind": "EXTERNAL", "system": "farmer-registry.farmer", "mode": "LENIENT",
                  "pattern": "^[A-Za-z0-9-]{3,64}$", "lookup": False},
    # Entities first: the plot is registered in the Farmer Registry before crop
    # activities are recorded on it, so there are no temporary plot IDs.
    "plot_id": {"kind": "EXTERNAL", "system": "farmer-registry.land", "mode": "LENIENT",
                "pattern": "^[A-Za-z0-9-]{3,64}$", "lookup": False},
    "da_id": {"kind": "EXTERNAL", "system": "da-registry", "mode": "LENIENT",
              "pattern": "^[A-Za-z0-9-]{3,64}$", "lookup": False},
    # The plot's woreda: where the crop season happened. It is the activity's
    # location (geo dimensions), so every figure can be rolled up by region,
    # zone and woreda. Required when a crop season is planned or sown; later
    # activities in the same crop season take it from there.
    "geo_lowest_level_value_id": {"kind": "GEO", "mode": "STRICT", "level": "woreda", "location": True},
}


def _refs(*extra: tuple[str, str]) -> dict:
    rules = dict(_REFERENCES)
    for field, attribute in extra:
        rules[field] = {"kind": "ATTRIBUTE", "attribute": attribute, "mode": "STRICT"}
    return rules


ACTIVITY_TYPES = [
    {
        "activity_type": "PLANNED",
        "display_name": "Crop planned",
        "description": "The farmer's plan for this crop on this plot this season.",
        "display_order": 10,
        "payload_schema": _schema(["area_ha", "geo_lowest_level_value_id"], {
            "variety": {"type": "string", "title": "Variety"},
            "area_ha": {**_AREA, "title": "Planned area (ha)"},
            "cropping_system": {"type": "string", "title": "Cropping system"},
            "planned_sowing_date": {**_DATE, "title": "Planned sowing date"},
            "planned_seed_kg": {**_KG, "title": "Planned seed (kg)"},
            "planned_fertilizers": {**_FERTILIZER_LIST, "title": "Planned fertilisers"},
            "expected_yield_qt_per_ha": {"type": "number", "minimum": 0, "maximum": 200,
                                         "title": "Expected yield (qt/ha)"},
        }),
        "is_repeatable": False,
        "max_backdate_days": 365,
        "allow_future_dated": False,
        "reference_rules": _refs(("cropping_system", "CROPPING_SYSTEM"),
                                 ("planned_fertilizers.fertilizer_type", "FERTILIZER_TYPE")),
        "ethiopian_date_fields": ["planned_sowing_date"],
    },
    {
        "activity_type": "LAND_PREPARED",
        "display_name": "Land prepared",
        "description": "Land preparation and irrigation set-up for the crop.",
        "display_order": 20,
        "payload_schema": _schema(["preparation_method"], {
            "preparation_method": {"type": "string", "title": "Preparation method"},
            "area_ha": {**_AREA, "title": "Area prepared (ha)"},
            "irrigated": {"type": "boolean", "title": "Irrigated"},
            "irrigation_source": {"type": "string", "title": "Irrigation source"},
            "irrigation_method": {"type": "string", "title": "Irrigation method"},
            "soil_fertility": {"type": "string", "title": "Soil fertility"},
        }),
        "is_repeatable": False,
        "requires_prior_types": ["PLANNED"],
        "sequence_enforcement": "WARN",
        "max_backdate_days": 365,
        "reference_rules": _refs(("preparation_method", "LAND_PREPARATION_METHOD"),
                                 ("irrigation_source", "IRRIGATION_SOURCE"),
                                 ("irrigation_method", "IRRIGATION_METHOD"),
                                 ("soil_fertility", "SOIL_FERTILITY")),
    },
    {
        "activity_type": "SOWN",
        "display_name": "Sown",
        "description": "The crop was sown. Verified by a supervisor.",
        "display_order": 30,
        "payload_schema": _schema(["area_ha", "seed_type", "geo_lowest_level_value_id"], {
            "variety": {"type": "string", "title": "Variety"},
            "area_ha": {**_AREA, "title": "Area sown (ha)"},
            "cropping_system": {"type": "string", "title": "Cropping system"},
            "seed_type": {"type": "string", "title": "Seed type"},
            "seed_source": {"type": "string", "title": "Seed source"},
            "seed_kg": {**_KG, "title": "Seed used (kg)"},
            "sowing_method": {"type": "string", "title": "Sowing method"},
            "fertilizers": _FERTILIZER_LIST,
            "compost_or_manure_used": {"type": "boolean", "title": "Compost or manure used"},
            "machinery_used": {"type": "array", "title": "Machinery used", "items": {"type": "string"}},
            "photo_document_id": {"type": "string", "title": "Geo-tagged photo"},
        }),
        "is_repeatable": False,
        "requires_prior_types": ["PLANNED"],
        "sequence_enforcement": "WARN",
        "due_rule": {"after_type": "PLANNED", "min_days": 0, "max_days": 60},
        "max_backdate_days": 180,
        "requires_verification": True,
        "reference_rules": _refs(("cropping_system", "CROPPING_SYSTEM"), ("seed_type", "SEED_TYPE"),
                                 ("seed_source", "SEED_SOURCE"), ("sowing_method", "SOWING_METHOD"),
                                 ("machinery_used", "FARM_MACHINERY"),
                                 ("fertilizers.fertilizer_type", "FERTILIZER_TYPE")),
    },
    {
        "activity_type": "CLUSTER_ENROLLED",
        "display_name": "Joined a cluster",
        "description": "The plot is farmed as part of a production cluster this season.",
        "display_order": 35,
        "payload_schema": _schema(["cluster_id"], {
            # The cluster is an entity in this registry's Cluster register
            # (name, zone, area, smallholders, water); here only which one.
            "cluster_id": {"type": "string", "title": "Cluster (code)"},
        }),
        "is_repeatable": False,
        "max_backdate_days": 365,
        "reference_rules": {**_refs(), "cluster_id": {
            "kind": "LOCAL_RECORD", "register": "Cluster", "match": "functional_record_id", "mode": "STRICT"}},
    },
    {
        "activity_type": "GROWTH_OBSERVED",
        "display_name": "Growth observed",
        "description": "A field visit: growth stage, crop condition and estimated yield.",
        "display_order": 40,
        "payload_schema": _schema(["growth_stage", "crop_condition"], {
            "growth_stage": {"type": "string", "title": "Growth stage"},
            "crop_condition": {"type": "string", "title": "Crop condition"},
            "area_ha": {**_AREA, "title": "Area under crop (ha)"},
            "estimated_yield_qt_per_ha": {"type": "number", "minimum": 0, "maximum": 200,
                                          "title": "Estimated yield (qt/ha)"},
            "photo_document_id": {"type": "string", "title": "Photo"},
        }),
        "is_repeatable": True,
        "requires_prior_types": ["SOWN"],
        "sequence_enforcement": "BLOCK",
        "max_backdate_days": 60,
        "reference_rules": _refs(("growth_stage", "CROP_GROWTH_STAGE"), ("crop_condition", "CROP_CONDITION")),
    },
    {
        "activity_type": "INFESTATION_REPORTED",
        "display_name": "Pest, disease or weed reported",
        "description": "An infestation observed on the crop, and what was done about it.",
        "display_order": 50,
        "payload_schema": _schema(["infestation_type", "agent", "severity"], {
            "infestation_type": {"type": "string", "title": "Type"},
            "agent": {"type": "string", "title": "Pest / disease / weed"},
            "severity": {"type": "string", "title": "Severity"},
            "area_ha": {**_AREA, "title": "Area affected (ha)"},
            "damage_percent": {**_PCT, "title": "Estimated damage (%)"},
            "action_taken": {"type": "string", "title": "Action taken"},
            "pesticide": {"type": "string", "title": "Pesticide used"},
            "pesticide_quantity_l": {"type": "number", "minimum": 0, "title": "Pesticide quantity (litres)"},
            "photo_document_id": {"type": "string", "title": "Photo"},
        }),
        "is_repeatable": True,
        "requires_prior_types": ["SOWN"],
        "sequence_enforcement": "BLOCK",
        "max_backdate_days": 60,
        "reference_rules": _refs(("infestation_type", "INFESTATION_TYPE"), ("agent", "INFESTATION_AGENT"),
                                 ("severity", "INFESTATION_SEVERITY"), ("action_taken", "PEST_CONTROL_ACTION")),
    },
    {
        "activity_type": "DAMAGE_REPORTED",
        "display_name": "Crop damage reported",
        "description": "Damage from weather or other causes (FAO WCA crop-loss causes).",
        "display_order": 55,
        "payload_schema": _schema(["cause", "loss_percent"], {
            "cause": {"type": "string", "title": "Cause"},
            "area_ha": {**_AREA, "title": "Area affected (ha)"},
            "loss_percent": {**_PCT, "title": "Estimated loss (%)"},
            "photo_document_id": {"type": "string", "title": "Photo"},
        }),
        "is_repeatable": True,
        "requires_prior_types": ["SOWN"],
        "sequence_enforcement": "BLOCK",
        "max_backdate_days": 60,
        "reference_rules": _refs(("cause", "CROP_DAMAGE_CAUSE")),
    },
    {
        "activity_type": "HARVESTED",
        "display_name": "Harvested",
        "description": "The harvest: area, quantity and what happened to it. Verified by a supervisor.",
        "display_order": 60,
        "payload_schema": _schema(["area_ha", "quantity_qt"], {
            "area_ha": {**_AREA, "title": "Area harvested (ha)"},
            "quantity_qt": {**_QT, "title": "Quantity harvested (quintals)"},
            "yield_qt_per_ha": {"type": "number", "minimum": 0, "title": "Yield (qt/ha, computed)"},
            "post_harvest_loss_qt": {**_QT, "title": "Post-harvest loss (qt)"},
            "stored_qt": {**_QT, "title": "Stored (qt)"},
            "sold_qt": {**_QT, "title": "Sold (qt)"},
            "consumed_qt": {**_QT, "title": "Consumed by household (qt)"},
            "seed_reserved_qt": {**_QT, "title": "Kept as seed (qt)"},
            "sale_price_birr_per_qt": {"type": "number", "minimum": 0, "title": "Sale price (birr/qt)"},
        }),
        "is_repeatable": False,
        "requires_prior_types": ["SOWN"],
        "sequence_enforcement": "BLOCK",
        "due_rule": {"after_type": "SOWN", "min_days": 90, "max_days": 180},
        "max_backdate_days": 120,
        "requires_verification": True,
        "reference_rules": _refs(),
    },
]

INDICATORS = [
    ("SOWN_AREA_BY_CROP", "Area sown by crop", "ha",
     {"measure": {"fn": "sum", "field": "area_sown_ha"}, "group_by": ["crop_year", "season", "crop"]}, 10),
    ("HARVEST_BY_CROP", "Quantity harvested by crop", "qt",
     {"measure": {"fn": "sum", "field": "quantity_harvested_qt"}, "group_by": ["crop_year", "season", "crop"]}, 20),
    ("AVERAGE_YIELD_BY_CROP", "Average yield by crop", "qt/ha",
     {"measure": {"fn": "avg", "field": "yield_qt_per_ha"}, "group_by": ["crop_year", "season", "crop"]}, 30),
    ("CROPS_BY_STAGE", "Crops by stage", "crops",
     {"measure": {"fn": "count", "field": "context_id"}, "group_by": ["crop_year", "season", "stage"]}, 40),
    ("FARMERS_REPORTING", "Farmers reporting", "farmers",
     {"measure": {"fn": "count_distinct", "field": "farmer_id"}, "group_by": ["crop_year", "season"]}, 50),
    ("INFESTED_CROPS", "Crops with infestations", "crops",
     {"measure": {"fn": "count", "field": "context_id"}, "group_by": ["crop_year", "season", "crop"],
      "filters": {"max_infestation_severity": ["SEV_LOW", "SEV_MEDIUM", "SEV_HIGH"]}}, 60),
    # By geography: "geo:<level>" groups on the crop season's location (named
    # Master Data levels) and adds the level's name.
    ("SOWN_AREA_BY_REGION", "Area sown by region and crop", "ha",
     {"measure": {"fn": "sum", "field": "area_sown_ha"}, "group_by": ["crop_year", "season", "geo:region", "crop"]}, 70),
    ("SOWN_AREA_BY_ZONE", "Area sown by zone and crop", "ha",
     {"measure": {"fn": "sum", "field": "area_sown_ha"}, "group_by": ["crop_year", "season", "geo:zone", "crop"]}, 80),
    ("SOWN_AREA_BY_WOREDA", "Area sown by woreda and crop", "ha",
     {"measure": {"fn": "sum", "field": "area_sown_ha"}, "group_by": ["crop_year", "season", "geo:woreda", "crop"]}, 90),
    ("HARVEST_BY_REGION", "Quantity harvested by region and crop", "qt",
     {"measure": {"fn": "sum", "field": "quantity_harvested_qt"},
      "group_by": ["crop_year", "season", "geo:region", "crop"]}, 100),
    ("AVERAGE_YIELD_BY_REGION", "Average yield by region and crop", "qt/ha",
     {"measure": {"fn": "avg", "field": "yield_qt_per_ha"}, "group_by": ["crop_year", "season", "geo:region", "crop"]}, 110),
    ("FARMERS_REPORTING_BY_WOREDA", "Farmers reporting by woreda", "farmers",
     {"measure": {"fn": "count_distinct", "field": "farmer_id"}, "group_by": ["crop_year", "season", "geo:woreda"]}, 120),
]

# ODK Central forms (inactive until an ODK project/form id is set for the environment).
ODK_FORMS = [
    {
        "odk_form_config_id": "c5000000-0000-4000-8000-0000000000f1",
        "odk_project_id": 1,
        "odk_form_id": "crop_sowing",
        "is_active": False,
        "mapping": {
            "activity_type": {"value": "SOWN"},
            "subject_type": {"value": "FARMER_ID"},
            "subject_id": "farmer/farmer_id",
            "occurred_on_ec": "sowing/sowing_date_ec",
            "payload": {
                "farmer_id": "farmer/farmer_id",
                "fayda_fan": "farmer/fayda_fan",
                "plot_id": "plot/plot_id",
                "crop_year": {"path": "season/crop_year", "transform": "integer"},
                "season": "season/season",
                "crop": "sowing/crop",
                "variety": "sowing/variety",
                "area_ha": {"path": "sowing/area_ha", "transform": "number"},
                "seed_type": "sowing/seed_type",
                "seed_source": "sowing/seed_source",
                "seed_kg": {"path": "sowing/seed_kg", "transform": "number"},
                "sowing_method": "sowing/sowing_method",
                "cropping_system": "sowing/cropping_system",
                "machinery_used": {"path": "sowing/machinery_used", "transform": "split"},
                "latitude": {"path": "plot/location", "transform": "geopoint_lat"},
                "longitude": {"path": "plot/location", "transform": "geopoint_lon"},
                "photo_document_id": {"path": "sowing/photo", "transform": "attachment"},
                "da_id": "meta_da/da_id",
                "geo_lowest_level_value_id": "plot/woreda",
            },
        },
    },
]


# Who takes part in each activity, by role. Each role reads a payload field and
# is typed by that field's reference rule: the farmer and plot are Farmer
# Registry identifiers, the development agent a DA Registry one, the cluster a
# record of this registry's Cluster register. The farmer is the primary role.
PARTICIPANT_ROLES = {
    "farmer": {"field": "farmer_id", "primary": True},
    "plot": {"field": "plot_id"},
    "development_agent": {"field": "da_id"},
    "cluster": {"field": "cluster_id"},
}
