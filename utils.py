import json
import re
from typing import Any, Dict, Optional


SKU_RE = re.compile(r"^[A-Za-z0-9]{5,6}$")


def is_valid_sku(sku: str) -> bool:
    return bool(SKU_RE.fullmatch((sku or "").strip()))


def normalize_ws(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s if s else None


def json_dumps(d: Dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def json_loads(s: str) -> Dict[str, Any]:
    return json.loads(s) if s else {}
