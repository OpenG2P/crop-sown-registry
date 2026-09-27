"""The code lists Master Data serves, read from the ETH country pack in openg2p-data.

Master Data loads packs/ETH/codelists/ and packs/ETH/domains/agriculture/ (with
geoSeed.domains: [agriculture]); the registry reads the lists there at runtime.
Tests read the same JSON, so a code this registry relies on and the pack does
not define fails here rather than on a live install.

The pack is found at $OPENG2P_DATA_DIR, else at ../openg2p-data beside this repo.
"""

import json
import os
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
DOMAINS = ("agriculture",)


def pack_dir() -> Optional[Path]:
    """The pack, or None when openg2p-data is simply not checked out beside this repo.

    An explicit $OPENG2P_DATA_DIR (as CI sets) that does not hold the pack is an
    error, not a reason to skip.
    """
    explicit = os.environ.get("OPENG2P_DATA_DIR")
    pack = Path(explicit or REPO.parent / "openg2p-data") / "packs" / "ETH"
    if pack.is_dir():
        return pack
    if explicit:
        raise FileNotFoundError(f"OPENG2P_DATA_DIR={explicit} has no packs/ETH")
    return None


def load_lists(pack: Path) -> dict[str, dict]:
    """attribute_code -> the list document, core lists plus DOMAINS."""
    dirs = [pack / "codelists"] + [pack / "domains" / d for d in DOMAINS]
    lists = {}
    for directory in dirs:
        for path in sorted(directory.glob("*.json")):
            doc = json.loads(path.read_text())
            lists[doc.get("attribute_code") or doc["attribute_id"]] = doc
    return lists


def codes(doc: dict) -> set[str]:
    return {v["value_code"] for v in doc["values"]}
