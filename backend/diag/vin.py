"""VIN handling: validation, offline WMI decode, optional online enrichment.

Nothing here is vehicle-specific. The car's own VIN is the only source used to
pick a manufacturer context, and every table below is a general reference
(ISO 3779 WMI prefixes, SAE J853 model-year codes). The online decode is
strictly best-effort: with no internet - the normal state in a parked car -
``decode_online`` reports ``available: False`` and the local decode still
stands on its own.

Why this module exists: the DTC lookup wants a manufacturer context so a code
can be shown with the maker's own wording when the bundled database has it.
Deriving that from the WMI keeps the app universal - no make, model or ECU is
baked in anywhere.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

#: VIN alphabet: 17 chars, no I, O or Q (ISO 3779).
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

#: Positions that carry a meaning we can read without a network call.
_POS_WMI = slice(0, 3)
_POS_YEAR_CODE = 9          # 0-indexed 10th character
_POS_PLANT = 10             # 0-indexed 11th character

#: SAE J853 model-year codes. The cycle repeats every 30 years, so a bare code
#: maps to several years; candidates are returned in newest-first order and the
#: caller is expected to say "candidate", never a fact.
_YEAR_CODES: Dict[str, List[int]] = {}
for _offset in range(0, 30):
    _char = "ABCDEFGHJKLMNPRSTVWXY123456789"[_offset]
    _YEAR_CODES.setdefault(_char, [])
    _year = 1980 + _offset
    while _year <= 2040:
        _YEAR_CODES[_char].append(_year)
        _year += 30
for _code in _YEAR_CODES:
    _YEAR_CODES[_code].sort(reverse=True)

#: WMI prefix -> manufacturer key used by the bundled DTC database.
#: Prefixes are matched longest-first, so a 3-character entry beats a
#: 2-character one. This is a general reference table, not a car profile.
WMI_MAKERS: Dict[str, str] = {
    # Volkswagen Group
    "WVW": "VOLKSWAGEN", "WV1": "VOLKSWAGEN", "WV2": "VOLKSWAGEN",
    "WV3": "VOLKSWAGEN", "1VW": "VOLKSWAGEN", "3VW": "VOLKSWAGEN",
    "WAU": "AUDI", "WA1": "AUDI", "TRU": "AUDI", "WUA": "AUDI",
    "TMB": "SKODA", "TMP": "SKODA",
    "VSS": "SEAT",
    "WP0": "PORSCHE", "WP1": "PORSCHE",
    "VW1": "VOLKSWAGEN",
    # BMW Group
    "WBA": "BMW", "WBX": "BMW", "WBS": "BMW", "WBY": "BMW",
    "4US": "BMW", "5UX": "BMW", "WMW": "MINI",
    # Mercedes-Benz
    "WDB": "MERCEDES-BENZ", "WDD": "MERCEDES-BENZ", "WDC": "MERCEDES-BENZ",
    "W1K": "MERCEDES-BENZ", "W1N": "MERCEDES-BENZ", "4JG": "MERCEDES-BENZ",
    "WMX": "MERCEDES-BENZ",
    # Stellantis / PSA / Renault
    "VF1": "RENAULT", "VF2": "RENAULT", "VF6": "RENAULT",
    "VF3": "PEUGEOT", "VF9": "PEUGEOT",
    "VF7": "CITROEN", "VR1": "CITROEN",
    "VXK": "OPEL", "W0L": "OPEL", "W0V": "OPEL", "WOL": "OPEL",
    "ZFA": "FIAT", "ZFC": "FIAT", "3C3": "FIAT",
    "ZAR": "ALFA ROMEO", "ZAM": "MASERATI",
    "ZAC": "JEEP", "1C4": "JEEP", "1J4": "JEEP", "3C4": "JEEP",
    "1C3": "CHRYSLER", "2C3": "CHRYSLER", "2B3": "DODGE", "1B3": "DODGE",
    "3D7": "DODGE", "1D3": "DODGE",
    # Ford
    "1FA": "FORD", "1FB": "FORD", "1FC": "FORD", "1FD": "FORD",
    "1FM": "FORD", "1FT": "FORD", "2FA": "FORD", "2FM": "FORD",
    "3FA": "FORD", "MAJ": "FORD", "WF0": "FORD",
    # General Motors
    "1G1": "CHEVROLET", "1G4": "CHEVROLET", "1GC": "CHEVROLET",
    "2G1": "CHEVROLET", "3G1": "CHEVROLET", "KL4": "CHEVROLET",
    "1GT": "GMC", "1GK": "GMC", "3GT": "GMC", "1GE": "CADILLAC",
    "1G6": "CADILLAC", "1GY": "CADILLAC", "1GH": "HOLDEN",
    # Toyota / Lexus
    "JTD": "TOYOTA", "JTE": "TOYOTA", "JTH": "LEXUS", "JTN": "TOYOTA",
    "JTM": "TOYOTA", "4T1": "TOYOTA", "4T3": "TOYOTA", "5TD": "TOYOTA",
    "5TF": "TOYOTA", "JT1": "TOYOTA", "SB1": "TOYOTA", "VNK": "TOYOTA",
    # Honda
    "JHM": "HONDA", "JHL": "HONDA", "JH4": "ACURA", "1HG": "HONDA",
    "2HG": "HONDA", "2HK": "HONDA", "3HG": "HONDA", "5FN": "HONDA",
    "SHH": "HONDA", "JHS": "HONDA",
    # Nissan / Renault-Nissan
    "JN1": "NISSAN", "JN3": "NISSAN", "JN6": "NISSAN", "JNK": "INFINITI",
    "1N4": "NISSAN", "1N6": "NISSAN", "5N1": "NISSAN", "VSK": "NISSAN",
    # Korean
    "KMH": "HYUNDAI", "KM8": "HYUNDAI", "5NP": "HYUNDAI", "5NM": "HYUNDAI",
    "KNA": "KIA", "KNB": "KIA", "KNC": "KIA", "KND": "KIA", "KNE": "KIA",
    "5XY": "KIA", "3KP": "KIA",
    "KLA": "DAEWOO", "KL1": "DAEWOO",
    # Japanese others
    "JM1": "MAZDA", "JM3": "MAZDA", "3MZ": "MAZDA", "4F2": "MAZDA",
    "JF1": "SUBARU", "JF2": "SUBARU", "4S3": "SUBARU", "4S4": "SUBARU",
    "JS2": "SUZUKI", "JS3": "SUZUKI", "JSA": "SUZUKI", "TSM": "SUZUKI",
    "JMB": "MITSUBISHI", "JMY": "MITSUBISHI", "4A3": "MITSUBISHI",
    "JA3": "MITSUBISHI", "JA4": "MITSUBISHI",
    "JTJ": "LEXUS", "JAA": "ISUZU", "JA1": "ISUZU", "MPA": "ISUZU",
    # Other VW-family / European
    "SAL": "LAND ROVER", "SAD": "LAND ROVER", "SAJ": "JAGUAR",
    "SCC": "LOTUS", "SA9": "MORGAN", "YV1": "VOLVO", "YV4": "VOLVO",
    "LVY": "VOLVO", "SUU": "VOLVO",
    "VWV": "VOLKSWAGEN",
    # EV / others
    "5YJ": "TESLA", "7SA": "TESLA", "LRW": "TESLA",
}

#: User-facing aliases accepted by DIAG_DTC_DEFAULT_MAKER and by the API.
MAKER_ALIASES: Dict[str, str] = {
    "vw": "VOLKSWAGEN", "volkswagen": "VOLKSWAGEN", "v w": "VOLKSWAGEN",
    "vag": "VOLKSWAGEN", "vw group": "VOLKSWAGEN",
    "audi": "AUDI", "skoda": "SKODA", "seat": "SEAT", "porsche": "PORSCHE",
    "merc": "MERCEDES-BENZ", "mercedes": "MERCEDES-BENZ",
    "mercedes-benz": "MERCEDES-BENZ", "benz": "MERCEDES-BENZ",
    "chevy": "CHEVROLET", "gm": "CHEVROLET", "gmc": "GMC",
    "landrover": "LAND ROVER", "land rover": "LAND ROVER",
    "alfa": "ALFA ROMEO", "mini": "MINI",
}


def normalize_vin(raw: Optional[str]) -> Optional[str]:
    """Uppercase and strip separators; returns None when there is no VIN."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-_]", "", str(raw)).upper()
    return cleaned or None


def validate(raw: Optional[str]) -> dict:
    """Check a VIN against ISO 3779 shape only.

    The check digit (position 9) is deliberately NOT verified: it is only
    mandatory in North America, so flagging every European VIN as "invalid"
    would be wrong. Shape plus a WMI hit is as far as an offline check can
    honestly go.
    """
    vin = normalize_vin(raw)
    if not vin:
        return {"valid": False, "vin": None, "reason": "no VIN reported by the ECU"}
    if len(vin) != 17:
        return {"valid": False, "vin": vin,
                "reason": "expected 17 characters, got %d" % len(vin)}
    if not _VIN_RE.match(vin):
        bad = sorted(set(c for c in vin if not re.match(r"[A-HJ-NPR-Z0-9]", c)))
        return {"valid": False, "vin": vin,
                "reason": "illegal VIN character(s): %s" % (", ".join(bad) or "?")}
    return {"valid": True, "vin": vin, "reason": None}


def wmi_maker(wmi: Optional[str]) -> Optional[str]:
    """Longest-prefix match against :data:`WMI_MAKERS`."""
    if not wmi:
        return None
    wmi = wmi.upper()
    for length in (3, 2):
        hit = WMI_MAKERS.get(wmi[:length])
        if hit:
            return hit
    return None


def resolve_maker(value: Optional[str]) -> Optional[str]:
    """Accept a code, a WMI or a human name and return the DTC database key."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    alias = MAKER_ALIASES.get(text.lower())
    if alias:
        return alias
    if len(text) >= 2:
        hit = wmi_maker(text)
        if hit:
            return hit
    return text.upper()


def maker_from_vin(raw: Optional[str]) -> Optional[str]:
    """Manufacturer context for DTC lookups, derived from the car's own VIN."""
    vin = normalize_vin(raw)
    if not vin or len(vin) < 3:
        return None
    return wmi_maker(vin[_POS_WMI])


def describe(raw: Optional[str]) -> dict:
    """Offline decode: everything the VIN itself proves, nothing more."""
    check = validate(raw)
    vin = check["vin"]
    out = {
        "vin": vin,
        "valid": check["valid"],
        "reason": check["reason"],
        "wmi": None,
        "maker": None,
        "model_year_code": None,
        "model_year_candidates": [],
        "plant_code": None,
        "serial": None,
        "decoded_offline": False,
    }
    if not vin or len(vin) != 17:
        return out
    out["decoded_offline"] = True
    out["wmi"] = vin[_POS_WMI]
    out["maker"] = wmi_maker(out["wmi"])
    out["plant_code"] = vin[_POS_PLANT] or None
    out["serial"] = vin[11:]
    if check["valid"]:
        year_char = vin[_POS_YEAR_CODE]
        out["model_year_code"] = year_char
        out["model_year_candidates"] = _YEAR_CODES.get(year_char, [])
    return out


def decode_online(raw: Optional[str], url: str, timeout: float = 6.0) -> dict:
    """Best-effort NHTSA vPIC decode. Never raises, never blocks the scan.

    ``url`` may contain ``{vin}``; otherwise the VIN is appended.
    """
    vin = normalize_vin(raw)
    result: dict = {"available": False, "source": url, "vin": vin,
                    "fields": {}, "error": None}
    if not vin:
        result["error"] = "no VIN to decode"
        return result
    if not url:
        result["error"] = "online decode disabled"
        return result
    endpoint = url.replace("{vin}", vin) if "{vin}" in url else url.rstrip("/") + "/" + vin
    try:
        request = urllib.request.Request(endpoint, headers={
            "User-Agent": "hudiy-diag/1 (offline-first diagnostics)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(64 * 1024).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        return result
    fields = _pick_vpic_fields(payload)
    result["available"] = bool(fields)
    result["fields"] = fields
    if not fields:
        result["error"] = "decode returned no usable fields"
    return result


def _pick_vpic_fields(payload: dict) -> dict:
    """Keep only the vPIC fields worth showing on a small screen."""
    results = payload.get("Results") if isinstance(payload, dict) else None
    if isinstance(results, list) and results and isinstance(results[0], dict):
        row = results[0]
    elif isinstance(payload, dict):
        row = payload
    else:
        return {}
    wanted = (
        "Make", "Model", "ModelYear", "Series", "Trim", "BodyClass",
        "FuelTypePrimary", "EngineCylinders", "DisplacementL",
        "EnginePower_kW", "EngineModel", "PlantCountry", "Manufacturer",
        "VehicleType", "ErrorText",
    )
    out = {}
    for key in wanted:
        value = row.get(key)
        if value not in (None, "", "0", 0):
            out[key] = value
    return out


def resolve(raw: Optional[str], *, maker_hint: Optional[str] = None,
            online_url: Optional[str] = None, online_enabled: bool = True,
            timeout: float = 6.0) -> dict:
    """Full VIN picture: local decode plus optional online enrichment.

    ``maker_hint`` (``DIAG_DTC_DEFAULT_MAKER``) wins over the WMI when set, so a
    user who knows their car is an odd VW-group rebadge can correct the guess.
    """
    info = describe(raw)
    info["maker"] = resolve_maker(maker_hint) or info["maker"]
    info["maker_source"] = ("configured" if maker_hint else
                            "vin-wmi" if info["maker"] else None)
    info["online"] = {"available": False, "skipped": True, "error": None,
                      "fields": {}, "source": None}
    if online_enabled and info["vin"]:
        online = decode_online(info["vin"], online_url or "", timeout=timeout)
        info["online"] = {"available": online["available"], "skipped": False,
                          "error": online["error"], "fields": online["fields"],
                          "source": online["source"]}
    return info
