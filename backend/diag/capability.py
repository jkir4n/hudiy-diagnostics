"""Compatibility sheet: everything this car reported, in one pasteable place.

A full scan discovers the car's capabilities at runtime (PID bitmaps, OBDMID
pages, Mode 09 infotypes, negative answers for Modes 02/0A) - this module
assembles those facts into a compact sheet a driver can paste into a GitHub
issue when asking "does this app work on my car". Nothing is probed here: the
sheet is built from an already-finished report dict, so ``GET /capability``
never touches the car itself.

Honesty rules, same as the report renderers: a mode that was not probed in
this scan says "not probed", a mode the ECU refused says "not supported" -
never zeros, never guesses. Identity fields appear only when the scan actually
captured them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional


def _hex_list(values) -> str:
    rendered = []
    for value in values or []:
        if isinstance(value, bool):
            rendered.append(str(int(value)))
        elif isinstance(value, int):
            rendered.append("0x%02X" % value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            rendered.append(text if text.lower().startswith("0x")
                            else "0x%s" % text.upper())
        else:
            rendered.append(str(value))
    return ", ".join(rendered) or "-"


def _query_state(queries: dict, command: str) -> dict:
    """What one fault/mode query observed: answered / not-supported / not-probed."""
    info = (queries or {}).get(command)
    if info is None:
        return {"state": "not-probed",
                "note": "this scan did not ask %s" % command}
    if info.get("supported") is False \
            or info.get("status") in ("no_data", "empty"):
        return {"state": "not-supported",
                "note": info.get("note") or "the ECU did not answer"}
    return {"state": "answered", "note": info.get("note") or ""}


def build_capability(report: dict, *, app_version: str = "unknown",
                     generated_at: Optional[str] = None,
                     data_source: str = "live",
                     lane_mode: str = "unknown") -> dict:
    """Assemble the compatibility sheet from a finished scan ``report``."""
    support = report.get("support") or {}
    codes = report.get("codes") or {}
    queries = codes.get("queries") or {}
    vehicle = report.get("vehicle") or {}
    scan = report.get("scan") or {}
    monitor_tests = report.get("monitor_tests") or []
    monitors = report.get("monitors") or {}

    # PID support, bank by bank ------------------------------------------------
    pids = support.get("pids") or {}
    bitmaps = support.get("bitmaps") or {}
    banks: List[dict] = []
    if isinstance(pids, dict):
        for command in sorted(pids):
            ids = pids.get(command) or []
            banks.append({
                "bank": command,
                "bitmap_hex": bitmaps.get(command),
                "pids": list(ids),
                "pids_hex": _hex_list(ids),
                "count": len(ids),
            })
    total_pids = sum(bank["count"] for bank in banks)

    # Mode 06: advertised pages vs monitors that actually answered -------------
    obdmid_pages = support.get("obdmid") or {}
    advertised = sorted({mid for ids in obdmid_pages.values()
                         for mid in (ids or [])})
    answered, unanswered = [], []
    for block in monitor_tests:
        mid = block.get("obdmid")
        row = {
            "obdmid": mid,
            "obdmid_hex": "0x%02X" % mid if isinstance(mid, int) else str(mid),
            "name": block.get("obdmid_name"),
            "answered": bool(block.get("ok")),
            "advertised": bool(block.get("advertised")),
            "tests": len(block.get("tests") or []),
        }
        (answered if row["answered"] else unanswered).append(row)

    # Observed mode support ----------------------------------------------------
    freeze = support.get("freeze_frame")
    modes = {
        "01": ({"state": "answered", "pid_count": total_pids,
                "note": "%d PIDs advertised" % total_pids}
               if banks else
               {"state": "not-probed", "pid_count": 0,
                "note": "discovery did not run in this scan"}),
        "02": ({"state": "answered" if freeze else "not-supported",
                "note": "freeze-frame bitmap answered" if freeze
                else "the ECU reports no freeze-frame support"}
               if freeze is not None else
               {"state": "not-probed",
                "note": "discovery did not run in this scan"}),
        "03": dict(_query_state(queries, "03"), label="stored DTCs"),
        "05": {"state": "not-probed", "label": "O2 sensor monitor (legacy)",
               "note": "no app version probes Mode 05; Mode 06 covers it"},
        "06": {"state": ("answered" if answered else
                         "not-supported" if monitor_tests else "not-probed"),
               "advertised_mids": len(advertised),
               "answered_mids": len(answered),
               "note": ("%d monitor(s) answered" % len(answered)) if answered
               else ("no monitor answered" if monitor_tests
                     else "the mode06 phase did not run in this scan")},
        "07": dict(_query_state(queries, "07"), label="pending DTCs"),
        "09": {"state": ("answered" if support.get("infotypes") else "not-probed"),
               "infotypes": list(support.get("infotypes") or []),
               "infotypes_hex": _hex_list(support.get("infotypes")),
               "note": ("infotypes %s reported"
                        % _hex_list(support.get("infotypes")))
               if support.get("infotypes")
               else "the 0900 probe did not run or was unanswered"},
        "0A": dict(_query_state(queries, "0A"), label="permanent DTCs"),
    }

    # Identity, only when captured ----------------------------------------------
    standard = vehicle.get("obd_standard") or {}
    identity = {
        "vin": vehicle.get("vin"),
        "ecu_name": vehicle.get("ecu_name"),
        "calid": vehicle.get("calid"),
        "cvn": vehicle.get("cvn"),
        "obd_standard": {"code": standard.get("code"),
                         "name": standard.get("name")},
    }

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    sections = scan.get("sections")
    return {
        "sheet": "hudiy-diagnostics/capability",
        "app_version": app_version,
        "generated_at": generated_at,
        "data_source": data_source,   # live | replay
        "lane_mode": lane_mode,       # proxy | standalone | replay | ...
        "coverage": {
            "sections": sections,     # None = full scan, else the filter used
            "full": sections is None,
            "scan_id": scan.get("id"),
            "duration_s": scan.get("duration_s"),
            "queries": scan.get("queries"),
            "timeouts": scan.get("timeouts"),
            "aborted": bool(scan.get("aborted")),
            "abort_reason": scan.get("abort_reason"),
        },
        "pid_support": {"banks": banks, "total": total_pids},
        "mode06": {
            "pages": sorted(obdmid_pages),
            "advertised_mids": advertised,
            "advertised_hex": _hex_list(advertised),
            "answered": answered,
            "unanswered": unanswered,
        },
        "modes": modes,
        "readiness_seen": bool((monitors.get("since_clear") or {}).get("ok")),
        "identity": identity,
        "notes": list(report.get("notes") or []),
    }


def render_text(cap: dict) -> str:
    """Plain-text sheet, suitable for pasting into a GitHub issue."""
    lines: List[str] = []
    bar = "=" * 68
    lines.append(bar)
    lines.append("  HUDIY DIAGNOSTICS - COMPATIBILITY SHEET")
    lines.append("  app v%s | %s | source: %s | lane: %s"
                 % (cap.get("app_version"), cap.get("generated_at"),
                    cap.get("data_source"), cap.get("lane_mode")))
    coverage = cap.get("coverage") or {}
    if coverage.get("full"):
        lines.append("  full scan %s (%s queries)"
                     % (coverage.get("scan_id"), coverage.get("queries")))
    else:
        lines.append("  PARTIAL coverage - sections read: %s"
                     % ", ".join(coverage.get("sections") or ["?"]))
    lines.append(bar)
    lines.append("")

    pid_support = cap.get("pid_support") or {}
    lines.append("MODE 01 PID SUPPORT (%d PIDs advertised)"
                 % (pid_support.get("total") or 0))
    lines.append("-" * 68)
    for bank in pid_support.get("banks") or []:
        lines.append("  %s [%s]: %s"
                     % (bank.get("bank"), bank.get("bitmap_hex") or "?",
                        bank.get("pids_hex")))
    if not pid_support.get("banks"):
        lines.append("  not probed in this scan")
    lines.append("")

    mode06 = cap.get("mode06") or {}
    lines.append("MODE 06 MONITORS (advertised: %s)"
                 % (mode06.get("advertised_hex") or "none"))
    lines.append("-" * 68)
    for row in (mode06.get("answered") or []) + (mode06.get("unanswered") or []):
        state = ("%d test(s)%s" % (row.get("tests"),
                                   " [advertised]" if row.get("advertised")
                                   else " [probed]")
                 if row.get("answered") else "not answered")
        lines.append("  MID %s %-34s %s"
                     % (row.get("obdmid_hex"), row.get("name") or "unknown",
                        state))
    if not (mode06.get("answered") or mode06.get("unanswered")):
        lines.append("  the mode06 phase did not run in this scan")
    lines.append("")

    lines.append("MODE SUPPORT (as observed)")
    lines.append("-" * 68)
    for mode in ("01", "02", "03", "05", "06", "07", "09", "0A"):
        info = (cap.get("modes") or {}).get(mode) or {}
        extra = ""
        if mode == "09" and info.get("infotypes_hex"):
            extra = " [%s]" % info["infotypes_hex"]
        line = "  Mode %-3s %-13s%s" % (mode, info.get("state", "?"), extra)
        if info.get("note"):
            line += " - %s" % info["note"]
        lines.append(line.rstrip())
    lines.append("  readiness monitors read: %s"
                 % ("yes" if cap.get("readiness_seen") else "no"))
    lines.append("")

    identity = cap.get("identity") or {}
    lines.append("VEHICLE / ECU IDENTITY (only what the car reported)")
    lines.append("-" * 68)
    for label, key in (("VIN", "vin"), ("ECU name", "ecu_name"),
                       ("CALID", "calid"), ("CVN", "cvn")):
        lines.append("  %-9s: %s" % (label, identity.get(key) or "not reported"))
    standard = identity.get("obd_standard") or {}
    lines.append("  OBD std  : %s"
                 % (standard.get("name") or "not reported"))
    lines.append("")

    notes = cap.get("notes") or []
    if notes:
        lines.append("SCAN NOTES")
        lines.append("-" * 68)
        for note in notes:
            lines.append("  - %s" % note)
        lines.append("")

    lines.append("generated %s by hudiy-diag v%s - paste into a GitHub issue as-is"
                 % (cap.get("generated_at"), cap.get("app_version")))
    return "\n".join(lines) + "\n"
