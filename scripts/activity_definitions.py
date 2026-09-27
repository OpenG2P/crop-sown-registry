"""The Crop Sown Registry's configuration, in one readable place.

`scripts/build_seed_sql.py` turns this into the seed SQL under
crop-sown-extension/.../meta_data/. Edit here, regenerate, commit both.

Fields follow the crop-sown sample registry, extended with items from the FAO
World Programme for the Census of Agriculture 2020 crop module and Ethiopia's
CSA Agricultural Sample Survey (Meher/Belg seasons, UREA/DAP/NPS fertilisers,
quintals). Codes are Ethiopia-defined lists (prefix CS_) except CROP_COMMODITY,
which comes from Master Data (the ETH country pack).
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
    "season": {"type": "string", "title": "Season", "enum": ["MEHER", "BELG", "IRRIGATION"]},
    "crop": {"type": "string", "title": "Crop"},
    "crop_other": {"type": "string", "title": "Crop (if other)"},
    "da_id": {"type": "string", "title": "Development agent ID"},
    "latitude": {"type": "string", "title": "Latitude"},
    "longitude": {"type": "string", "title": "Longitude"},
    "geo_lowest_level_value_id": {"type": "string", "title": "Kebele"},
    "remarks": {"type": "string", "title": "Remarks", "maxLength": 2000},
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
    "season": {"kind": "ATTRIBUTE", "attribute": "CS_SEASON", "mode": "STRICT"},
    "variety": {"kind": "ATTRIBUTE", "attribute": "CS_SEED_VARIETY", "mode": "LENIENT"},
    # Identifiers held by other registries: format only, never blocking.
    "farmer_id": {"kind": "EXTERNAL", "system": "farmer-registry.farmer", "mode": "LENIENT",
                  "pattern": "^[A-Za-z0-9-]{3,64}$", "lookup": False},
    "plot_id": {"kind": "EXTERNAL", "system": "farmer-registry.land", "mode": "LENIENT",
                "pattern": "^[A-Za-z0-9-]{3,64}$", "temporary_prefix": "TMP-", "lookup": False},
    "da_id": {"kind": "EXTERNAL", "system": "da-registry", "mode": "LENIENT",
              "pattern": "^[A-Za-z0-9-]{3,64}$", "lookup": False},
    "geo_lowest_level_value_id": {"kind": "GEO", "mode": "LENIENT"},
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
        "payload_schema": _schema(["area_ha"], {
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
        "reference_rules": _refs(("cropping_system", "CS_CROPPING_SYSTEM"),
                                 ("planned_fertilizers.fertilizer_type", "CS_FERTILIZER_TYPE")),
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
        "reference_rules": _refs(("preparation_method", "CS_LAND_PREPARATION"),
                                 ("irrigation_source", "CS_IRRIGATION_SOURCE"),
                                 ("irrigation_method", "CS_IRRIGATION_METHOD"),
                                 ("soil_fertility", "SOIL_FERTILITY")),
    },
    {
        "activity_type": "SOWN",
        "display_name": "Sown",
        "description": "The crop was sown. Verified by a supervisor.",
        "display_order": 30,
        "payload_schema": _schema(["area_ha", "seed_type"], {
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
        "reference_rules": _refs(("cropping_system", "CS_CROPPING_SYSTEM"), ("seed_type", "CS_SEED_TYPE"),
                                 ("seed_source", "CS_SEED_SOURCE"), ("sowing_method", "CS_SOWING_METHOD"),
                                 ("machinery_used", "CS_MACHINERY"),
                                 ("fertilizers.fertilizer_type", "CS_FERTILIZER_TYPE")),
    },
    {
        "activity_type": "CLUSTER_ENROLLED",
        "display_name": "Joined a cluster",
        "description": "The plot is farmed as part of a production cluster this season.",
        "display_order": 35,
        "payload_schema": _schema(["cluster_id"], {
            "cluster_id": {"type": "string", "title": "Cluster ID"},
            "cluster_name": {"type": "string", "title": "Cluster name"},
            "agro_ecological_zone": {"type": "string", "title": "Agro-ecological zone"},
            "cluster_area_ha": {**_AREA, "title": "Cluster area (ha)"},
            "smallholders_count": {"type": "integer", "minimum": 1, "title": "Smallholders in cluster"},
            "water_source": {"type": "string", "title": "Water source"},
        }),
        "is_repeatable": False,
        "max_backdate_days": 365,
        "reference_rules": _refs(("agro_ecological_zone", "CS_AGRO_ECOLOGICAL_ZONE"),
                                 ("water_source", "WATER_SOURCE")),
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
        "reference_rules": _refs(("growth_stage", "CS_GROWTH_STAGE"), ("crop_condition", "CS_CROP_CONDITION")),
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
        "reference_rules": _refs(("infestation_type", "CS_INFESTATION_TYPE"), ("agent", "CS_INFESTATION_AGENT"),
                                 ("severity", "CS_SEVERITY"), ("action_taken", "CS_CONTROL_ACTION")),
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
        "reference_rules": _refs(("cause", "CS_DAMAGE_CAUSE")),
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

# Ethiopia-defined code lists owned by this registry. CROP_COMMODITY,
# SOIL_FERTILITY and WATER_SOURCE come from Master Data's agriculture domain.
CODE_LISTS = {
    "CS_SEASON": ("Season", [("MEHER", "Meher (main rains)"), ("BELG", "Belg (short rains)"),
                             ("IRRIGATION", "Irrigation (dry season)")]),
    "CS_CROPPING_SYSTEM": ("Cropping system", [("PURE", "Pure stand"), ("MIXED", "Mixed"),
                                               ("INTERCROPPED", "Intercropped")]),
    "CS_LAND_PREPARATION": ("Land preparation method", [("OXEN", "Oxen plough"), ("TRACTOR", "Tractor"),
                                                        ("MANUAL", "Manual (hoe)"), ("ZERO_TILLAGE", "Zero tillage")]),
    "CS_IRRIGATION_SOURCE": ("Irrigation source", [("RIVER", "River diversion"), ("DAM", "Dam / reservoir"),
                                                   ("WELL", "Hand-dug or deep well"), ("SPRING", "Spring"),
                                                   ("POND", "Pond / water harvesting")]),
    "CS_IRRIGATION_METHOD": ("Irrigation method", [("FURROW", "Furrow"), ("FLOOD", "Flood / basin"),
                                                   ("SPRINKLER", "Sprinkler"), ("DRIP", "Drip")]),
    "CS_SEED_TYPE": ("Seed type", [("IMPROVED", "Improved"), ("LOCAL", "Local"), ("HYBRID", "Hybrid")]),
    "CS_SEED_SOURCE": ("Seed source", [("COOPERATIVE", "Cooperative / union"), ("GOVERNMENT", "Government / DA"),
                                       ("MARKET", "Market"), ("OWN_SAVED", "Own saved"), ("NGO", "NGO / project"),
                                       ("NEIGHBOUR", "Neighbour / exchange")]),
    "CS_SOWING_METHOD": ("Sowing method", [("BROADCAST", "Broadcast"), ("ROW", "Row planting"),
                                           ("TRANSPLANT", "Transplanting")]),
    "CS_FERTILIZER_TYPE": ("Fertiliser type", [("UREA", "Urea"), ("DAP", "DAP"), ("NPS", "NPS"), ("NPSB", "NPSB"),
                                               ("NPSZnB", "NPSZnB"), ("COMPOST", "Compost"), ("MANURE", "Manure")]),
    "CS_MACHINERY": ("Machinery", [("TRACTOR", "Tractor"), ("ROW_PLANTER", "Row planter"),
                                   ("THRESHER", "Thresher"), ("COMBINE", "Combine harvester"),
                                   ("SPRAYER", "Sprayer"), ("WATER_PUMP", "Water pump")]),
    "CS_GROWTH_STAGE": ("Growth stage", [("EMERGENCE", "Emergence"), ("VEGETATIVE", "Vegetative"),
                                         ("FLOWERING", "Flowering"), ("GRAIN_FILLING", "Grain filling"),
                                         ("MATURITY", "Maturity")]),
    "CS_CROP_CONDITION": ("Crop condition", [("GOOD", "Good"), ("FAIR", "Fair"), ("POOR", "Poor"),
                                             ("FAILED", "Failed")]),
    "CS_INFESTATION_TYPE": ("Infestation type", [("PEST", "Pest"), ("DISEASE", "Disease"), ("WEED", "Weed")]),
    "CS_INFESTATION_AGENT": ("Pest, disease or weed", [
        ("FALL_ARMYWORM", "Fall armyworm"), ("DESERT_LOCUST", "Desert locust"), ("STALK_BORER", "Stalk borer"),
        ("APHIDS", "Aphids"), ("WHEAT_RUST", "Wheat rust"), ("MAIZE_LETHAL_NECROSIS", "Maize lethal necrosis"),
        ("SEPTORIA", "Septoria"), ("STRIGA", "Striga"), ("PARTHENIUM", "Parthenium"), ("OTHER", "Other")]),
    "CS_SEVERITY": ("Severity", [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")]),
    "CS_CONTROL_ACTION": ("Action taken", [("CHEMICAL", "Chemical"), ("BIOLOGICAL", "Biological"),
                                           ("CULTURAL", "Cultural / manual"), ("NONE", "None")]),
    "CS_DAMAGE_CAUSE": ("Damage cause", [("DROUGHT", "Drought / moisture stress"), ("FLOOD", "Flood / waterlogging"),
                                         ("HAIL", "Hail"), ("FROST", "Frost"), ("WIND", "Wind"),
                                         ("WILDLIFE", "Wildlife / livestock"), ("OTHER", "Other")]),
    "CS_AGRO_ECOLOGICAL_ZONE": ("Agro-ecological zone", [("BEREHA", "Bereha (hot lowland)"), ("KOLLA", "Kolla (lowland)"),
                                                         ("WEYNA_DEGA", "Weyna Dega (midland)"), ("DEGA", "Dega (highland)"),
                                                         ("WURCH", "Wurch (cold highland)")]),
    "CS_SEED_VARIETY": ("Seed variety", [
        ("TEFF_QUNCHO", "Teff – Quncho"), ("TEFF_BOSET", "Teff – Boset"), ("WHEAT_KAKABA", "Wheat – Kakaba"),
        ("WHEAT_DANDAA", "Wheat – Danda'a"), ("MAIZE_BH661", "Maize – BH661"), ("MAIZE_BH546", "Maize – BH546"),
        ("BARLEY_HB1307", "Barley – HB1307"), ("SORGHUM_MELKAM", "Sorghum – Melkam")]),
}

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
      "filters": {"max_infestation_severity": ["LOW", "MEDIUM", "HIGH"]}}, 60),
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
            },
        },
    },
]
