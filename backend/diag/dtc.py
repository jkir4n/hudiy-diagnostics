"""Bundled DTC text lookup (Wal33D/dtc-database, MIT).

The database ships with the app so a parked car with no internet still gets
plain-English code text. It is read-only and optional: if the file is missing
the store reports why and every lookup returns ``available: False`` instead of
raising, so the scan degrades to raw codes rather than failing.

Layout (schema v1, verified against the bundled file):

    dtc_definitions(code, manufacturer, description, type, locale,
                    is_generic, source_file)  PK (code, manufacturer, locale)
    statistics(manufacturer, total_codes, unique_codes, p_codes, b_codes,
               c_codes, u_codes)

``manufacturer='GENERIC'`` rows carry the SAE J2012 wording every car gets;
maker rows carry that maker's own wording for the same code. A lookup returns
both, so the report can show the generic text and, when the maker is known,
the maker's extra detail - never one silently replacing the other.

Manufacturer names in the file are its own spelling (``MERCEDES``, ``CHEVY``,
``GM``); :meth:`DtcStore.resolve_manufacturer` maps the names VIN decoding
produces onto those keys, and falls back to "no maker context" when there is
nothing to match. Nothing about any specific car is hardcoded here.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from typing import Dict, Iterable, List, Optional, Tuple

#: Codes are P/B/C/U + 4 hex-ish digits (J2012). Suffixes like ``P0301-00``
#: exist on some ECUs, so the trailing part is kept but not required.
_CODE_RE = re.compile(r"^([PBCU])([0-9A-F]{4})")

#: Names VIN/WMI decoding produces -> names the database uses.
MANUFACTURER_ALIASES: Dict[str, str] = {
    "MERCEDES-BENZ": "MERCEDES",
    "MERCEDES BENZ": "MERCEDES",
    "CHEVROLET": "CHEVY",
    "GENERAL MOTORS": "GM",
    "GMC": "GMC",
    "VOLKSWAGEN": "VOLKSWAGEN",
    "VW": "VOLKSWAGEN",
    "LAND ROVER": "OTHER",
    "ALFA ROMEO": "OTHER",
    "MASERATI": "OTHER",
    "TESLA": "OTHER",
    "MINI": "OTHER",
    "PORSCHE": "OTHER",
    "VOLVO": "OTHER",
    "PEUGEOT": "OTHER",
    "CITROEN": "OTHER",
    "RENAULT": "OTHER",
    "OPEL": "OTHER",
    "FIAT": "OTHER",
    "SKODA": "OTHER",
    "SEAT": "OTHER",
    "DAEWOO": "OTHER",
    "ISUZU": "OTHER",
    "HOLDEN": "OTHER",
    "LOTUS": "OTHER",
}


def normalize_code(raw: Optional[str]) -> Optional[str]:
    """Uppercase, strip whitespace/dashes and validate the J2012 shape."""
    if raw is None:
        return None
    text = str(raw).strip().upper().replace(" ", "").replace("-", "")
    if not text:
        return None
    match = _CODE_RE.match(text)
    if not match:
        return None
    return match.group(1) + match.group(2)


class DtcStore:
    """Read-only access to the bundled DTC database."""

    def __init__(self, path=None, locale: str = "en", enabled: bool = True,
                 timeout: float = 5.0) -> None:
        self.path = str(path) if path else None
        self.locale = locale or "en"
        self.enabled = bool(enabled)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._reason: Optional[str] = None
        self._manufacturers: Optional[List[str]] = None

    # --- lifecycle ----------------------------------------------------------
    def _connect(self) -> Optional[sqlite3.Connection]:
        if self._conn is not None:
            return self._conn
        if not self.enabled:
            self._reason = "DTC lookup disabled by configuration"
            return None
        if not self.path:
            self._reason = "no DTC database path configured"
            return None
        try:
            uri = "file:%s?mode=ro" % self.path
            self._conn = sqlite3.connect(uri, uri=True,
                                         timeout=self.timeout,
                                         check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # A stale copy must not silently serve half a row.
            self._conn.execute("PRAGMA query_only = ON")
        except sqlite3.Error as exc:
            self._reason = "cannot open %s: %s" % (self.path, exc)
            self._conn = None
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    @property
    def available(self) -> bool:
        return self._connect() is not None

    def status(self) -> dict:
        """Everything a health endpoint needs to explain this store."""
        info = {
            "available": False,
            "path": self.path,
            "locale": self.locale,
            "reason": None,
            "codes": None,
            "manufacturers": None,
        }
        conn = self._connect()
        if conn is None:
            info["reason"] = self._reason
            return info
        try:
            info["codes"] = conn.execute(
                "SELECT COUNT(*) FROM dtc_definitions").fetchone()[0]
            info["manufacturers"] = conn.execute(
                "SELECT COUNT(*) FROM statistics").fetchone()[0]
            info["available"] = True
        except sqlite3.Error as exc:
            info["reason"] = "schema mismatch: %s" % exc
        return info

    # --- reference data -----------------------------------------------------
    def manufacturers(self) -> List[str]:
        conn = self._connect()
        if conn is None:
            return []
        with self._lock:
            if self._manufacturers is None:
                try:
                    rows = conn.execute(
                        "SELECT manufacturer FROM statistics "
                        "ORDER BY manufacturer").fetchall()
                    self._manufacturers = [row["manufacturer"] for row in rows]
                except sqlite3.Error:
                    self._manufacturers = []
            return list(self._manufacturers)

    def resolve_manufacturer(self, name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Map a decoded maker name onto a key this database actually has.

        Returns ``(key, how)`` where ``how`` explains the match - ``"exact"``,
        ``"alias"``, ``"contains"`` - or ``(None, None)`` when the database has
        no rows for that maker. No match means the report shows generic text
        plus a "manufacturer-specific" note; it never invents wording.
        """
        if not name:
            return None, None
        wanted = str(name).strip().upper()
        if not wanted:
            return None, None
        known = self.manufacturers()
        if not known:
            return None, None
        upper = {key.upper(): key for key in known}
        if wanted in upper:
            return upper[wanted], "exact"
        alias = MANUFACTURER_ALIASES.get(wanted)
        if alias and alias in upper:
            return upper[alias], "alias"
        for key_upper, key in upper.items():
            if key_upper and (key_upper in wanted or wanted in key_upper):
                return key, "contains"
        return None, None

    # --- lookups ------------------------------------------------------------
    def _row_for(self, conn: sqlite3.Connection, code: str,
                 manufacturer: Optional[str]) -> Optional[dict]:
        sql = ("SELECT code, manufacturer, description, type, locale, "
               "is_generic, source_file FROM dtc_definitions "
               "WHERE code = ? AND locale = ? AND manufacturer = ? LIMIT 1")
        row = conn.execute(sql, (code, self.locale, manufacturer)).fetchone()
        if row is None:
            return None
        return {
            "code": row["code"],
            "manufacturer": row["manufacturer"],
            "description": row["description"],
            "type": row["type"],
            "generic": bool(row["is_generic"]),
            "source": row["source_file"],
        }

    def lookup(self, code: Optional[str], maker: Optional[str] = None) -> dict:
        """Generic + maker-specific text for one code. Never raises."""
        normalized = normalize_code(code)
        result: dict = {
            "available": False,
            "code": normalized or (str(code).strip().upper() if code else None),
            "raw_code": code,
            "found": False,
            "generic": None,
            "manufacturer_specific": None,
            "manufacturer": None,
            "manufacturer_match": None,
            "reason": None,
        }
        conn = self._connect()
        if conn is None:
            result["reason"] = self._reason
            return result
        result["available"] = True
        if normalized is None:
            result["reason"] = ("%r is not a P/B/C/U + 4 digit diagnostic code"
                                % (code,))
            return result

        key, how = self.resolve_manufacturer(maker)
        result["manufacturer"] = key
        result["manufacturer_match"] = how
        try:
            with self._lock:
                generic = self._row_for(conn, normalized, "GENERIC")
                specific = None
                if key and key.upper() != "GENERIC":
                    specific = self._row_for(conn, normalized, key)
        except sqlite3.Error as exc:
            result["available"] = False
            result["reason"] = "query failed: %s" % exc
            return result

        result["generic"] = generic
        result["manufacturer_specific"] = specific
        result["found"] = bool(generic or specific)
        if not result["found"]:
            result["reason"] = ("%s is not in the bundled database (SAE J2012 "
                                "generic set plus maker rows)" % normalized)
        elif specific is None and key:
            result["reason"] = ("no %s-specific row for %s; showing the generic "
                                "J2012 description" % (key, normalized))
        return result

    def lookup_many(self, codes: Iterable[str], maker: Optional[str] = None) -> List[dict]:
        return [self.lookup(code, maker=maker) for code in codes]

    def stats(self) -> dict:
        conn = self._connect()
        if conn is None:
            return {"available": False, "reason": self._reason, "rows": []}
        try:
            with self._lock:
                rows = conn.execute(
                    "SELECT * FROM statistics ORDER BY manufacturer").fetchall()
        except sqlite3.Error as exc:
            return {"available": False, "reason": str(exc), "rows": []}
        return {"available": True, "reason": None,
                "rows": [dict(row) for row in rows]}


def default_store(cfg) -> DtcStore:
    """Build the store from configuration (keeps callers out of path logic)."""
    return DtcStore(
        path=getattr(cfg, "dtc_db_path", None),
        locale=getattr(cfg, "dtc_locale", "en") or "en",
        enabled=bool(getattr(cfg, "dtc_lookup_enabled", True)),
    )
