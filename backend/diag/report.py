"""Report rendering: turn a finished scan dict into shareable text, CSV, JSON.

The scan report is the product's payload - it is what a driver hands to a
mechanic, so the renderers are deliberately boring and total: every section of
the report dict has a place in the output, and anything the ECU did not answer
is printed as "not supported" or "no data" rather than omitted. A reader must
never be able to tell the difference between "the car is clean" and "we failed
to ask" by seeing an empty area.

Nothing here is vehicle-specific: the sections are driven by the report's own
support bits.

Formats: ``json`` (machine), ``txt`` (mechanic/print), ``csv`` (spreadsheet).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Tuple

#: Report formats this module can render, with the file extension and MIME type.
FORMATS = {
    "json": (".json", "application/json"),
    "txt": (".txt", "text/plain"),
    "csv": (".csv", "text/csv"),
}


def _num(value) -> str:
    """Format a number for a human: drop useless decimals, keep the unit."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9:
            return "%d" % round(value)
        return ("%.3f" % value).rstrip("0").rstrip(".")
    return str(value)


def _rule(char: str = "-", width: int = 72) -> str:
    return char * width


def _stamp(report: dict) -> str:
    started = (report.get("scan") or {}).get("started_at")
    if isinstance(started, (int, float)):
        return datetime.fromtimestamp(started, tz=timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %Z")
    return str(started or "unknown")


def filename_for(report: dict, fmt: str = "txt") -> str:
    """A stable, sortable file name for an exported report."""
    ext, _ = FORMATS.get(fmt, FORMATS["txt"])
    scan = report.get("scan") or {}
    scan_id = str(scan.get("id") or "unknown")
    started = scan.get("started_at")
    if isinstance(started, (int, float)):
        stamp = datetime.fromtimestamp(started).strftime("%Y%m%d-%H%M%S")
    else:
        stamp = "undated"
    return "hudiy-diag-%s-%s%s" % (stamp, scan_id, ext)


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------

def render_json(report: dict, indent: int = 2) -> str:
    return json.dumps(report, indent=indent, sort_keys=False, default=str)


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

def _text_verdict(lines: List[str], report: dict) -> None:
    readiness = report.get("readiness") or {}
    lines.append("VERDICT")
    lines.append(_rule())
    headline = readiness.get("headline") or "no verdict available"
    lines.append("  %s" % headline)
    for reason in readiness.get("reasons") or []:
        lines.append("    - %s" % reason)
    if readiness.get("inputs_missing"):
        lines.append("    - not read: %s" % ", ".join(readiness["inputs_missing"]))
    disclaimer = readiness.get("disclaimer") or report.get("disclaimer")
    if disclaimer:
        lines.append("  %s" % disclaimer)
    lines.append("")


def _text_vehicle(lines: List[str], report: dict) -> None:
    vehicle = report.get("vehicle") or {}
    if not vehicle:
        return
    lines.append("VEHICLE / ECU IDENTITY")
    lines.append(_rule())
    lines.append("  VIN        : %s" % (vehicle.get("vin") or "not reported"))
    if vehicle.get("vin") and not vehicle.get("vin_17_chars", True):
        lines.append("               (VIN is %d characters - ECU returned a partial VIN)"
                     % len(str(vehicle["vin"])))
    lines.append("  ECU name   : %s" % (vehicle.get("ecu_name") or "not reported"))
    lines.append("  CALID      : %s" % (vehicle.get("calid") or "not reported"))
    cvn = vehicle.get("cvn")
    if isinstance(cvn, (list, tuple)):
        cvn = " ".join(str(item) for item in cvn)
    lines.append("  CVN        : %s" % (cvn or "not reported"))
    standard = vehicle.get("obd_standard") or {}
    if standard.get("code") is not None or standard.get("name"):
        lines.append("  OBD std    : %s (%s)"
                     % (standard.get("name") or "unknown", standard.get("code") or "-"))
    vin_info = vehicle.get("vin_info") or {}
    if vin_info.get("maker"):
        source = vin_info.get("maker_source")
        lines.append("  Maker hint : %s%s"
                     % (vin_info["maker"],
                        " (from VIN)" if source == "vin-wmi" else
                        " (configured)" if source == "configured" else ""))
    years = vin_info.get("model_year_candidates") or []
    if years:
        lines.append("  Model year : %s" % ", ".join(str(year) for year in years))
    lines.append("")


def _text_codes(lines: List[str], report: dict) -> None:
    codes = report.get("codes") or {}
    summary = codes.get("summary") or {}
    lines.append("FAULT CODES")
    lines.append(_rule())
    lines.append("  stored: %d   pending: %d   permanent: %d   MIL: %s   reported count: %s"
                 % (len(codes.get("stored") or []),
                    len(codes.get("pending") or []),
                    len(codes.get("permanent") or []),
                    _num(codes.get("mil")),
                    _num(codes.get("dtc_count"))))
    groups = (("stored", codes.get("stored")), ("pending", codes.get("pending")),
              ("permanent", codes.get("permanent")))
    any_code = False
    for label, entries in groups:
        for entry in entries or []:
            any_code = True
            lookup = entry.get("lookup") or {}
            text = None
            for key in ("generic", "manufacturer_specific"):
                row = lookup.get(key) or {}
                if row.get("description"):
                    text = row["description"]
                    break
            lines.append("  [%-9s] %-7s %s" % (label, entry.get("code", "?"),
                                               text or "(no text available)"))
            if lookup.get("manufacturer_specific"):
                row = lookup["manufacturer_specific"]
                lines.append("             %s-specific: %s"
                             % (row.get("manufacturer", "maker"), row["description"]))
            elif lookup.get("manufacturer"):
                lines.append("             (no %s-specific wording; generic shown)"
                             % lookup["manufacturer"])
            elif lookup.get("available"):
                lines.append("             (generic wording unavailable)")
            elif lookup.get("reason"):
                lines.append("             (lookup off: %s)" % lookup["reason"])
    if not any_code:
        lines.append("  no fault codes reported by the ECU")
    queries = codes.get("queries") or {}
    for command, info in queries.items():
        if info.get("supported") is False or info.get("status") in ("no_data", "empty"):
            lines.append("  %s: not supported by this ECU (%s)"
                         % (command, info.get("note") or "no data"))
    lines.append("")


def _text_readiness(lines: List[str], report: dict) -> None:
    monitors = report.get("monitors") or {}
    since = monitors.get("since_clear") or {}
    lines.append("EMISSION READINESS (since DTCs cleared)")
    lines.append(_rule())
    if not since.get("ok"):
        lines.append("  not read: %s" % (since.get("error") or "no data"))
        lines.append("")
        return
    for group, key in (("common", "common"), ("specific", "specific")):
        entries = since.get(key) or []
        if not entries:
            continue
        lines.append("  %s:" % group)
        for monitor in entries:
            if monitor.get("available") is False:
                state = "not supported" if monitor.get("state") != "reserved" else "reserved"
            elif monitor.get("complete") is True:
                state = "complete"
            elif monitor.get("complete") is False:
                state = "INCOMPLETE"
            else:
                state = "unknown"
            lines.append("    %-34s %s" % (monitor.get("label") or monitor.get("key"), state))
    cycle = monitors.get("this_cycle") or {}
    if cycle.get("ok"):
        incomplete = [m.get("label") for m in
                      list(cycle.get("common") or []) + list(cycle.get("specific") or [])
                      if m.get("available") is True and m.get("complete") is False]
        lines.append("  this drive cycle, incomplete: %s"
                     % (", ".join(incomplete) if incomplete else "none"))
    lines.append("")


def _text_monitor_tests(lines: List[str], report: dict) -> None:
    tests = report.get("monitor_tests") or []
    lines.append("MODE 06 MONITOR TESTS")
    lines.append(_rule())
    if not tests:
        lines.append("  no Mode 06 results in this scan")
        lines.append("")
        return
    for block in tests:
        mid = block.get("obdmid")
        name = block.get("obdmid_name") or "unknown"
        summary = block.get("summary") or {}
        if not block.get("ok"):
            lines.append("  MID 0x%02X %-28s not answered (%s)"
                         % (mid or 0, name, block.get("error") or block.get("status")))
            continue
        lines.append("  MID 0x%02X %-28s %d test(s), %d outside limits%s"
                     % (mid or 0, name, summary.get("tests", 0),
                        summary.get("outside_limits", 0),
                        "  [advertised]" if block.get("advertised") else "  [probed]"))
        for entry in block.get("tests") or []:
            unit = (entry.get("value") or {}).get("unit") or ""
            lines.append("    TID 0x%02X %-26s value %s %s  (min %s max %s)  %s"
                         % (entry.get("tid") or 0,
                            entry.get("tid_name") or "unknown",
                            _num((entry.get("value") or {}).get("value")), unit,
                            _num((entry.get("min") or {}).get("value")),
                            _num((entry.get("max") or {}).get("value")),
                            entry.get("judgement") or "unknown"))
            lines.append("        UAS %s (%s)  raw %s"
                         % (entry.get("uas"), entry.get("uas_name"),
                            entry.get("raw_hex")))
        if summary.get("ambiguous"):
            lines.append("    NOTE: %s" % summary.get("ambiguous_note"))
        if summary.get("residual_hex"):
            lines.append("    residual bytes: %s" % summary["residual_hex"])
    lines.append("")


def _text_live(lines: List[str], report: dict) -> None:
    live = report.get("live") or []
    lines.append("LIVE VALUES (diagnostic snapshot)")
    lines.append(_rule())
    if not live:
        lines.append("  no supported live PID answered")
        lines.append("")
        return
    for entry in live:
        if not entry.get("ok"):
            lines.append("  %-38s no data (%s)"
                         % (entry.get("name") or entry.get("pid"), entry.get("error") or ""))
            continue
        lines.append("  %-38s %s %s"
                     % (entry.get("name") or ("PID %s" % entry.get("pid")),
                        _num(entry.get("value")), entry.get("unit") or ""))
    lines.append("")


def _text_support(lines: List[str], report: dict) -> None:
    support = report.get("support") or {}
    pids = sorted(support.get("pids") or [])
    obdmid = support.get("obdmid") or {}
    lines.append("RUNTIME DISCOVERY (this car, this scan)")
    lines.append(_rule())
    lines.append("  PIDs supported: %d %s"
                 % (len(pids), ", ".join("0x%02X" % pid for pid in pids) or "-"))
    for key, ids in sorted(obdmid.items()):
        lines.append("  Mode 06 %s: %s"
                     % (key, ", ".join("0x%02X" % mid for mid in (ids or [])) or "-"))
    lines.append("  freeze frame: %s" % ("supported"
                                         if support.get("freeze_frame") else "not supported"))
    lines.append("")


def _text_notes(lines: List[str], report: dict) -> None:
    notes = report.get("notes") or []
    if not notes:
        return
    lines.append("NOTES")
    lines.append(_rule())
    for note in notes:
        lines.append("  - %s" % note)
    lines.append("")


def _text_provenance(lines: List[str], report: dict) -> None:
    scan = report.get("scan") or {}
    lines.append("SCAN PROVENANCE")
    lines.append(_rule())
    lines.append("  scan id    : %s" % scan.get("id"))
    lines.append("  host       : %s" % scan.get("host"))
    lines.append("  started    : %s" % _stamp(report))
    lines.append("  duration   : %s s" % _num(scan.get("duration_s")))
    lines.append("  queries    : %s   timeouts: %s   retries: %s   failures: %s"
                 % (_num(scan.get("queries")), _num(scan.get("timeouts")),
                    _num(scan.get("retries")), _num(scan.get("failures"))))
    if scan.get("aborted"):
        lines.append("  ABORTED    : %s" % scan.get("abort_reason"))
    steps = scan.get("step_log") or []
    for step in steps:
        if isinstance(step, dict):
            lines.append("    %-6s %-8s %s"
                         % (step.get("command", ""), step.get("status", ""),
                            step.get("label", "")))
        else:
            lines.append("    %s" % step)
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines.append("")
    lines.append("report generated %s by hudiy-diag v1" % generated)


def render_text(report: dict, title: str = "HUDIY DIAGNOSTICS REPORT") -> str:
    lines: List[str] = []
    scan = report.get("scan") or {}
    lines.append(_rule("="))
    lines.append("  %s" % title)
    lines.append("  %s" % _stamp(report))
    if scan.get("aborted"):
        lines.append("  ** SCAN ABORTED: %s **" % scan.get("abort_reason"))
    lines.append(_rule("="))
    lines.append("")
    _text_verdict(lines, report)
    _text_vehicle(lines, report)
    _text_codes(lines, report)
    _text_readiness(lines, report)
    _text_monitor_tests(lines, report)
    _text_live(lines, report)
    _text_support(lines, report)
    _text_notes(lines, report)
    _text_provenance(lines, report)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

CSV_HEADER = ("section", "item", "code", "value", "unit", "status", "detail")


def _csv_verdict(rows: List[Tuple], report: dict) -> None:
    readiness = report.get("readiness") or {}
    rows.append(("verdict", "headline", "", readiness.get("verdict") or "", "",
                 readiness.get("headline") or "", ""))
    for reason in readiness.get("reasons") or []:
        rows.append(("verdict", "reason", "", "", "", "info", reason))
    for missing in readiness.get("inputs_missing") or []:
        rows.append(("verdict", "input_missing", "", "", "", "not-read", missing))


def _csv_vehicle(rows: List[Tuple], report: dict) -> None:
    vehicle = report.get("vehicle") or {}
    if not vehicle:
        return
    for field in ("vin", "ecu_name", "calid", "cvn"):
        value = vehicle.get(field)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item) for item in value)
        rows.append(("vehicle", field, "", value or "", "", "reported" if value
                     else "not-reported", ""))
    standard = vehicle.get("obd_standard") or {}
    rows.append(("vehicle", "obd_standard", "", standard.get("name") or "",
                 "", "reported" if standard.get("name") else "not-reported",
                 standard.get("code") or ""))


def _csv_codes(rows: List[Tuple], report: dict) -> None:
    codes = report.get("codes") or {}
    for label in ("stored", "pending", "permanent"):
        for entry in codes.get(label) or []:
            lookup = entry.get("lookup") or {}
            generic = (lookup.get("generic") or {}).get("description") or ""
            specific = (lookup.get("manufacturer_specific") or {}).get("description") or ""
            rows.append(("codes", label, entry.get("code") or "",
                         generic or specific,
                         "", "manufacturer-specific" if specific else "generic",
                         specific if specific else (lookup.get("reason") or "")))
    rows.append(("codes", "summary", "", str(len(codes.get("stored") or [])), "",
                 "stored", "MIL=%s reported_count=%s"
                 % (_num(codes.get("mil")), _num(codes.get("dtc_count")))))


def _csv_readiness(rows: List[Tuple], report: dict) -> None:
    since = (report.get("monitors") or {}).get("since_clear") or {}
    for group in ("common", "specific"):
        for monitor in since.get(group) or []:
            if monitor.get("available") is False:
                state = "not-supported"
            elif monitor.get("complete") is True:
                state = "complete"
            elif monitor.get("complete") is False:
                state = "incomplete"
            else:
                state = "unknown"
            rows.append(("readiness", group, monitor.get("key") or "",
                         "", "", state, monitor.get("label") or ""))


def _csv_monitor_tests(rows: List[Tuple], report: dict) -> None:
    for block in report.get("monitor_tests") or []:
        mid = block.get("obdmid")
        item = "MID 0x%02X" % (mid or 0)
        if not block.get("ok"):
            rows.append(("mode06", item, "", "", "not-answered",
                         block.get("error") or block.get("status") or "", ""))
            continue
        for entry in block.get("tests") or []:
            rows.append(("mode06", item, "TID 0x%02X" % (entry.get("tid") or 0),
                         _num((entry.get("value") or {}).get("value")),
                         (entry.get("value") or {}).get("unit") or "",
                         entry.get("judgement") or "unknown",
                         "%s | min %s max %s | UAS %s (%s) | raw %s"
                         % (entry.get("tid_name") or "unknown",
                            _num((entry.get("min") or {}).get("value")),
                            _num((entry.get("max") or {}).get("value")),
                            entry.get("uas"), entry.get("uas_name"),
                            entry.get("raw_hex"))))


def _csv_live(rows: List[Tuple], report: dict) -> None:
    for entry in report.get("live") or []:
        rows.append(("live", entry.get("name") or ("PID %s" % entry.get("pid")),
                     "0x%02X" % (entry.get("pid") or 0),
                     _num(entry.get("value")) if entry.get("ok") else "",
                     entry.get("unit") or "",
                     "ok" if entry.get("ok") else "no-data",
                     entry.get("error") or entry.get("raw_hex") or ""))


def _csv_notes(rows: List[Tuple], report: dict) -> None:
    for note in report.get("notes") or []:
        rows.append(("notes", "", "", "", "", "note", note))


def render_csv(report: dict) -> str:
    rows: List[Tuple] = []
    _csv_verdict(rows, report)
    _csv_vehicle(rows, report)
    _csv_codes(rows, report)
    _csv_readiness(rows, report)
    _csv_monitor_tests(rows, report)
    _csv_live(rows, report)
    _csv_notes(rows, report)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def render(report: dict, fmt: str) -> str:
    """Render ``report`` in ``fmt`` (json/txt/csv). Unknown fmt -> txt."""
    key = (fmt or "txt").strip().lower().lstrip(".")
    if key == "json":
        return render_json(report)
    if key == "csv":
        return render_csv(report)
    return render_text(report)


def content_type(fmt: str) -> str:
    key = (fmt or "txt").strip().lower().lstrip(".")
    return FORMATS.get(key, FORMATS["txt"])[1]


def write_report(report: dict, fmt: str, directory) -> str:
    """Render and write a report file; returns the absolute path written.

    The caller owns the directory choice (``config.report_dir`` is runtime
    state); this function only makes sure it exists.
    """
    import os

    key = (fmt or "txt").strip().lower().lstrip(".")
    if key not in FORMATS:
        key = "txt"
    directory = str(directory)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename_for(report, key))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render(report, key))
    return path


def summary_line(report: dict) -> str:
    """One line for a header/notification: verdict plus code counts."""
    readiness = report.get("readiness") or {}
    codes = report.get("codes") or {}
    total = len(codes.get("stored") or []) + len(codes.get("pending") or []) \
        + len(codes.get("permanent") or [])
    return "%s - %d code(s)%s" % (
        readiness.get("headline") or "scan incomplete", total,
        " (scan aborted)" if (report.get("scan") or {}).get("aborted") else "")
