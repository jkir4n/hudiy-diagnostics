"""Feature decoders: turn a correlated response into UI-ready structures.

Everything here is data-in/data-out and JSON-serialisable - no I/O, no clock,
no globals - so the whole surface can be replayed from the Phase-1 fixtures in
unit tests without a car attached.

Design rules that come straight from the Phase-1 findings:

* **Availability and completeness are separate facts.** A monitor that the car
  does not implement is reported as ``available: false`` and is *never* counted
  as a failure (AGENTS.md 4a: Mode 0A and Mode 02 are simply unsupported on the
  reference ECU). "Not supported" is grey, not red.
* **Completeness bits are inverted** (0 = test complete) while availability
  bits are not (1 = supported). Byte order is documented in
  docs/OBD2_DIAGNOSTICS_RESEARCH.md section 2 and is exercised by tests.
* **Unknown identifiers are surfaced, not dropped.** A car that reports an
  OBDMID or TID this table has never seen still appears in the report with its
  raw values.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from . import framing, names
from .protocol import DecodedResponse

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def bit_is_set(byte: int, bit: int) -> bool:
    """True when ``bit`` (0 = LSB) is set in ``byte``."""
    return bool(byte & (1 << bit))


def bitmap_to_ids(bitmap: Sequence[int], base: int) -> List[int]:
    """Decode an MSB-first capability bitmap into the identifiers it claims.

    ``bitmap`` is the data after the echoed PID. Bit 7 of the first byte claims
    the *lowest* identifier of the range, so the MSB maps to ``base + 1``
    (bit 7 of the first byte of ``01 00`` means "PID 0x01 supported"). Ground
    truth: ``4140CCD20000`` decodes to 0141/0142/0145/0146/0149/014A/014C/014F
    (fixtures/m02_freezeframe_decoded.json).
    """
    found: List[int] = []
    for index, byte in enumerate(bitmap):
        for bit in range(8):
            if bit_is_set(byte, 7 - bit):
                found.append(base + index * 8 + bit + 1)
    return found


def u16(chunk: Sequence[int]) -> int:
    return (chunk[0] << 8) | chunk[1]


def signed16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def scale_uas(raw: int, uas: Optional[int]) -> dict:
    """Apply the UAS scaling table (J1979 Appendix E) to a raw 16-bit value.

    An unknown UAS ID is reported honestly: the raw value is returned with
    ``scaled: None`` so the UI shows the number it actually has instead of a
    number this code made up.
    """
    entry = names.UAS_IDS.get(uas) if isinstance(uas, int) else None
    if entry is None:
        return {"raw": raw, "scaled": None, "unit": None,
                "uas": uas, "known": False}
    value = signed16(raw) if entry["signed"] else raw
    return {
        "raw": raw,
        "scaled": value * entry["scale"] + entry["offset"],
        "unit": entry["unit"],
        "uas": uas,
        "known": True,
        "note": entry["note"],
    }


# --------------------------------------------------------------------------
# Mode 01 - supported PID bitmaps
# --------------------------------------------------------------------------


def supported_pids(response: DecodedResponse, base: Optional[int] = None) -> dict:
    """Decode a ``01 00/20/40/...`` capability bitmap."""
    if not response.ok:
        return {"ok": False, "status": response.status,
                "error": response.error, "pids": []}
    if base is None:
        base = response.pid if response.pid is not None else 0x00
    pids = bitmap_to_ids(response.payload, base)
    return {
        "ok": True,
        "status": response.status,
        "range_start": base,
        "bitmap_hex": response.payload.hex().upper(),
        "pids": pids,
        "pids_named": [{"pid": p, "name": names.pid_name(p)} for p in pids],
        # 0x20, 0x40 ... means "ask for the next range".
        "next_range": (base + 0x20) if (base + 0x20) in pids else None,
    }


# --------------------------------------------------------------------------
# Mode 01 PID 01 / 41 - monitor status (readiness)
# --------------------------------------------------------------------------

#: (bit, key, label) for the compression-ignition C/D monitor map.
DIESEL_MONITORS = (
    (7, "egr_vvt", "EGR and/or VVT system"),
    (6, "pm_filter", "PM filter (DPF) monitoring"),
    (5, "exhaust_gas_sensor", "Exhaust gas sensor"),
    (4, "reserved_c4", "Reserved"),
    (3, "boost_pressure", "Boost pressure"),
    (2, "reserved_c2", "Reserved"),
    (1, "nox_scr", "NOx / SCR monitor"),
    (0, "nmhc_catalyst", "NMHC catalyst"),
)

#: Same byte positions, spark-ignition interpretation.
SPARK_MONITORS = (
    (7, "egr_vvt", "EGR and/or VVT system"),
    (6, "o2_sensor_heater", "Oxygen sensor heater"),
    (5, "o2_sensor", "Oxygen sensor"),
    (4, "gpf", "Gasoline particulate filter"),
    (3, "secondary_air", "Secondary air system"),
    (2, "evaporative", "Evaporative system"),
    (1, "heated_catalyst", "Heated catalyst"),
    (0, "catalyst", "Catalyst"),
)

#: b7 reserved, b6..b4 completeness, b3 engine type, b2..b0 availability.
COMMON_MONITORS = (
    (2, 6, "components", "Components"),
    (1, 5, "fuel_system", "Fuel system"),
    (0, 4, "misfire", "Misfire"),
)


def monitor_status(response: DecodedResponse) -> dict:
    """Decode ``01 01`` / ``01 41`` into the readiness structure.

    ``response.pid`` tells 01 from 41; both share the encoding, but 41 never
    repeats the MIL state (byte A is forced to 0).
    """
    if not response.ok:
        return {"ok": False, "status": response.status,
                "error": response.error, "error_name": names.nrc_name(response.nrc)
                if response.nrc is not None else None}
    if len(response.payload) < 4:
        return {"ok": False, "status": "short",
                "error": "PID 01 needs 4 data bytes, got %d" % len(response.payload)}

    a, b, c, d = response.payload[:4]
    is_drive_cycle = (response.pid == 0x41)
    mil_on = (not is_drive_cycle) and bit_is_set(a, 7)
    dtc_count = 0 if is_drive_cycle else (a & 0x7F)
    diesel = bit_is_set(b, 3)

    common = []
    for avail_bit, complete_bit, key, label in COMMON_MONITORS:
        available = bit_is_set(b, avail_bit)
        complete = not bit_is_set(b, complete_bit)   # 0 = complete
        common.append({
            "key": key,
            "label": label,
            "available": available,
            "complete": complete if available else None,
            # Not supported is neither ready nor not-ready: it is simply N/A.
            "state": ("na" if not available else ("complete" if complete else "incomplete")),
            "kind": "common",
        })

    table = DIESEL_MONITORS if diesel else SPARK_MONITORS
    specific = []
    for bit, key, label in table:
        available = bit_is_set(c, bit)
        complete = not bit_is_set(d, bit)
        reserved = key.startswith("reserved_")
        specific.append({
            "key": key,
            "label": label,
            "available": available,
            "complete": complete if available else None,
            "state": ("reserved" if reserved and not available else
                      "na" if not available else
                      "complete" if complete else "incomplete"),
            "kind": "specific",
        })

    return {
        "ok": True,
        "status": response.status,
        "pid": response.pid,
        "drive_cycle": is_drive_cycle,
        "mil_on": mil_on,
        "dtc_count": dtc_count,
        "engine_type": "compression_ignition" if diesel else "spark_ignition",
        "raw_hex": response.payload[:4].hex().upper(),
        "common": common,
        "specific": specific,
    }


# --------------------------------------------------------------------------
# DTCs (Mode 03 / 07 / 0A and the freeze-frame DTC of PID 02)
# --------------------------------------------------------------------------


def decode_dtc_pair(first: int, second: int) -> dict:
    """Two bytes -> ``{'code': 'P0123', 'category': 'Powertrain'}``."""
    letter = names.DTC_CATEGORIES[(first >> 6) & 0x03][0]
    code = "%s%02X%02X" % (letter, first & 0x3F, second)
    return {
        "code": code,
        "category": names.dtc_category_label(letter),
        "bytes": "%02X%02X" % (first, second),
        "known": code != "%s0000" % letter,
    }


def _dtc_bytes(payload: bytes) -> tuple:
    """Split a Mode 03/07/0A payload into DTC bytes and the parse assumption.

    ECUs disagree about the leading count byte and about tail padding, so the
    shape is *detected* and the assumption is reported alongside the result.
    """
    body = bytes(payload)
    assumption = "no count byte"
    if not body:
        return b"", assumption
    # A count byte is present iff the remaining length is exactly 2 x count.
    if len(body) % 2 == 1 and body[0] * 2 == len(body) - 1:
        return body[1:], "leading DTC count byte = %d" % body[0]
    if len(body) % 2 == 1:
        body = body[1:]
        assumption = "dropped leading byte (odd length, not a valid count)"
    return body, assumption


def dtc_list(response: DecodedResponse, mode: Optional[int] = None) -> dict:
    """Decode stored / pending / permanent DTC lists."""
    if not response.ok:
        return {
            "ok": False,
            "status": response.status,
            "error": response.error,
            "nrc_name": names.nrc_name(response.nrc) if response.nrc is not None else None,
            "mode": mode,
            "codes": [],
            "empty_is_good": True,   # a refused/unavailable mode is not a fault
        }

    raw, assumption = _dtc_bytes(response.payload)
    codes: List[dict] = []
    for index in range(0, len(raw) - 1, 2):
        entry = decode_dtc_pair(raw[index], raw[index + 1])
        if not entry["known"]:
            continue  # 0000 is padding, not a code
        codes.append(entry)

    return {
        "ok": True,
        "status": response.status,
        "mode": mode if mode is not None else (response.sid - 0x40 if response.sid else None),
        "raw_hex": bytes(response.payload).hex().upper(),
        "parse_assumption": assumption,
        "count_hex": "%02X" % response.payload[0] if response.payload else "",
        "codes": codes,
        "code_count": len(codes),
    }


def freeze_frame_dtc(response: DecodedResponse) -> dict:
    """``01 02`` -> the DTC that stored the freeze frame (``0000`` = none)."""
    if not response.ok:
        return {"ok": False, "status": response.status, "error": response.error,
                "stored": False, "dtc": None}
    if len(response.payload) < 2:
        return {"ok": False, "status": "short",
                "error": "PID 02 needs 2 data bytes", "stored": False, "dtc": None}
    entry = decode_dtc_pair(response.payload[0], response.payload[1])
    return {
        "ok": True,
        "status": response.status,
        "stored": entry["known"],
        "dtc": entry if entry["known"] else None,
        "raw_hex": response.payload[:2].hex().upper(),
    }


# --------------------------------------------------------------------------
# Mode 09 - vehicle information
# --------------------------------------------------------------------------


def info_types(response: DecodedResponse) -> dict:
    """``09 00`` -> the Mode 09 infotypes this ECU supports."""
    if not response.ok:
        return {"ok": False, "status": response.status, "error": response.error,
                "infotypes": []}
    # ``09 00`` lists infotypes starting at 0x01, so the bitmap base is 0x00.
    found = bitmap_to_ids(response.payload, 0x00)
    return {
        "ok": True,
        "status": response.status,
        "bitmap_hex": response.payload.hex().upper(),
        "infotypes": found,
    }


def _ascii_records(payload: bytes) -> dict:
    """Decode a Mode 09 ASCII record set (VIN, CAL-ID, ECU name).

    Layout is ``<NODI> <content...>`` where NODI is the number of data items;
    the ECU pads the tail with ``AA``/``00``/``FF``. Padding is stripped only
    from the tail and the raw ASCII is always preserved.
    """
    body = bytes(payload)
    nodi = body[0] if body and body[0] <= 0x10 else None
    content = body[1:] if nodi is not None else body
    stripped = framing.strip_tail_padding(content)
    text = framing.bytes_to_ascii(stripped)
    return {
        "nodi": nodi,
        "ascii": text,
        "ascii_raw": framing.bytes_to_ascii(content),
        "bytes_hex": body.hex().upper(),
        "stripped_hex": stripped.hex().upper(),
    }


def vehicle_info(response: DecodedResponse) -> dict:
    """Decode any Mode 09 identity response by its infotype."""
    if not response.ok:
        return {"ok": False, "status": response.status, "error": response.error,
                "infotype": response.pid if response.pid is not None else None,
                "value": None}
    infotype = response.pid
    result = {
        "ok": True,
        "status": response.status,
        "infotype": infotype,
        "value": None,
        "detail": None,
    }
    if infotype == 0x02:                       # VIN
        detail = _ascii_records(response.payload)
        detail["vin"] = detail["ascii"].strip()
        detail["valid_length"] = len(detail["vin"]) == 17
        result["detail"] = detail
        result["value"] = detail["vin"]
    elif infotype == 0x04:                     # Calibration ID
        detail = _ascii_records(response.payload)
        result["detail"] = detail
        result["value"] = detail["ascii"].strip()
    elif infotype == 0x06:                     # Calibration verification numbers
        detail = _ascii_records(response.payload)
        field = detail["stripped_hex"] or detail["bytes_hex"]
        cvns = [field[i:i + 8] for i in range(0, len(field) - 7, 8)]
        detail["cvn_list"] = cvns
        result["detail"] = detail
        result["value"] = ",".join(cvns) if cvns else None
    elif infotype == 0x0A:                     # ECU name
        detail = _ascii_records(response.payload)
        result["detail"] = detail
        result["value"] = detail["ascii"].strip()
    else:
        detail = _ascii_records(response.payload)
        result["detail"] = detail
        result["value"] = detail["ascii"].strip() or detail["bytes_hex"]
    return result


# --------------------------------------------------------------------------
# Mode 06 - on-board monitoring test results
# --------------------------------------------------------------------------

#: Bytes in one Mode 06 test record after the SID and OBDMID.
#: TID(1) + UASID(1) + value(2) + min(2) + max(2).
UM_GROUP_SIZE = 8


def monitor_test_bitmap(response: DecodedResponse, base: Optional[int] = None) -> dict:
    """``06 00`` / ``06 20`` -> which OBDMIDs the ECU claims to have results for.

    The reference car proves the bitmap is not trustworthy on its own: ``0600``
    claimed only OBDMID 0x01 (plus the 0x20 range marker) yet ``0631`` and
    ``0685`` answered with real numbers. The scan therefore treats this as a
    *hint* and probes the known OBDMID list as well.
    """
    if not response.ok:
        return {"ok": False, "status": response.status, "error": response.error,
                "obdmids": []}
    if base is None:
        base = (response.pid or 0x00)
    found = bitmap_to_ids(response.payload, base)
    return {
        "ok": True,
        "status": response.status,
        "range_start": base,
        "bitmap_hex": response.payload.hex().upper(),
        "obdmids": found,
        "obdmids_named": [{"obdmid": m, "name": names.obdmid_name(m)} for m in found],
        "next_range": (base + 0x20) if (base + 0x20) in found else None,
    }


def monitor_tests(response: DecodedResponse, obdmid: Optional[int] = None) -> dict:
    """Decode a ``06 <OBDMID>`` response into test records.

    Record layout (docs/OBD2_DIAGNOSTICS_RESEARCH.md section 1.7)::

        46 <OBDMID> <TID> <UASID> <value hi> <value lo> <min hi> <min lo> <max hi> <max lo>
           (the 8-byte group repeats for further test results)

    Two things are deliberately *not* done here:

    * No min/max comparison is allowed to fail a scan. On the reference car the
      raw bytes for some MIDs give ``min > max`` under this layout, which is
      exactly the ambiguity Phase 1 recorded; it is reported as
      ``layout_ambiguous`` instead of being turned into a verdict.
    * Nothing is invented for a trailing partial group - the leftover bytes are
      preserved as ``residual_hex`` for a human to look at.
    """
    if obdmid is None:
        obdmid = response.pid
    base = {
        "ok": False,
        "status": response.status,
        "obdmid": obdmid,
        "obdmid_name": names.obdmid_name(obdmid) if obdmid is not None else None,
        "tests": [],
        "residual_hex": "",
        "layout_ambiguous": False,
    }
    if not response.ok:
        base["error"] = response.error
        base["supported"] = False
        return base

    data = bytes(response.payload)
    groups = len(data) // UM_GROUP_SIZE
    residual = data[groups * UM_GROUP_SIZE:]
    tests: List[dict] = []
    implausible = 0
    for index in range(groups):
        chunk = data[index * UM_GROUP_SIZE:(index + 1) * UM_GROUP_SIZE]
        tid, uas = chunk[0], chunk[1]
        value_raw, min_raw, max_raw = u16(chunk[2:4]), u16(chunk[4:6]), u16(chunk[6:8])
        entry = {
            "tid": tid,
            "tid_name": names.tid_name(tid),
            "uas": uas,
            "uas_name": names.uas_name(uas),
            "value": scale_uas(value_raw, uas),
            "min": scale_uas(min_raw, uas),
            "max": scale_uas(max_raw, uas),
            "value_raw": value_raw,
            "min_raw": min_raw,
            "max_raw": max_raw,
            "raw_hex": chunk.hex().upper(),
        }
        # A structural sanity check that does NOT depend on scaling: under the
        # documented layout min should never exceed max. If it does, either the
        # car uses a different layout (documented ambiguity for OBDMID 0x85) or
        # the record is manufacturer-specific - both are worth flagging.
        entry["within_limits"] = (
            (min_raw <= value_raw <= max_raw)
            if min_raw <= max_raw else None)
        if min_raw > max_raw:
            implausible += 1
        tests.append(entry)

    base.update({
        "ok": True,
        "supported": True,
        "record_count": groups,
        "records_reported": groups,
        "tests": tests,
        "residual_hex": residual.hex().upper(),
        "layout_ambiguous": implausible > 0,
        "parse_note": ("min > max in %d record(s): layout is ambiguous, "
                       "raw bytes preserved" % implausible) if implausible else "",
    })
    return base


# --------------------------------------------------------------------------
# Mode 01 scalar PIDs
# --------------------------------------------------------------------------


def pid_value(response: DecodedResponse) -> dict:
    """Decode a scalar Mode 01 PID using the explicit scaling table.

    Only PIDs in :data:`names.PID_SCALING` get a physical value; everything
    else is returned as the raw bytes plus a hex string, so unsupported or
    exotic PIDs never render as a wrong number.
    """
    pid = response.pid
    result = {
        "ok": response.ok,
        "status": response.status,
        "pid": pid,
        "name": names.pid_name(pid) if pid is not None else None,
        "raw_hex": bytes(response.payload).hex().upper(),
        "value": None,
        "unit": None,
    }
    if not response.ok:
        result["error"] = response.error
        return result
    scaling = names.PID_SCALING.get(pid) if pid is not None else None
    if scaling and response.payload:
        unit, scale, offset = scaling
        raw = response.payload[0] if len(response.payload) == 1 else u16(response.payload)
        result["value"] = raw * scale + offset
        result["unit"] = unit
        result["raw"] = raw
    elif response.payload:
        result["value"] = int.from_bytes(bytes(response.payload), "big")
        result["unit"] = ""
        result["raw"] = result["value"]
    return result


def summarize_codes(responses: Iterable[dict]) -> dict:
    """Roll several DTC lists into one picture for the report."""
    stored, pending, permanent = [], [], []
    buckets = {"stored": stored, "pending": pending, "permanent": permanent}
    for item in responses:
        mode = item.get("mode")
        key = {3: "stored", 7: "pending", 10: "permanent"}.get(mode)
        if key:
            buckets[key].extend(item.get("codes", []))
    total = len(stored) + len(pending) + len(permanent)
    return {
        "stored": stored,
        "pending": pending,
        "permanent": permanent,
        "total": total,
        "clear": total == 0,
    }
