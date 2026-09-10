"""The readiness verdict: the four-input arithmetic, in one place.

An inspection station does not read words, it does arithmetic
(docs/DIESEL_READINESS_FINDINGS.md section 2). Four inputs decide the line:

1. **warning-light state**          - Mode 01 PID 01 byte A bit 7
2. **stored code count**            - byte A bits 6-0, cross-checked against Mode 03
3. **supported-but-incomplete monitors** - bytes B/C availability vs B/D completeness
4. **pending / permanent codes**    - Mode 07 and Mode 0A

Two rules keep this honest:

* A monitor the car does not implement is *not* an incomplete monitor. It is
  excluded from the count entirely, so an unsupported system can never make a
  healthy car look unready (and vice versa: a supported monitor the ECU does
  not implement cannot be "ready" either - it is simply N/A).
* The allowance (how many incomplete monitors are tolerated) is a *local
  inspection rule*, not a technical fact, so it comes from the config table and
  the verdict carries the rule's own caveat and the global disclaimer.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from . import config

VERDICT_READY = "ready"
VERDICT_NOT_READY = "not_ready"
VERDICT_MIL_ON = "mil_on"
VERDICT_CODES_PRESENT = "codes_present"
VERDICT_UNKNOWN = "unknown"

#: Prepended to the headline so the UI never has to invent wording.
HEADLINES = {
    VERDICT_READY: "Monitor readiness complete",
    VERDICT_NOT_READY: "Monitors not yet complete",
    VERDICT_MIL_ON: "Warning light is on",
    VERDICT_CODES_PRESENT: "Fault codes are stored",
    VERDICT_UNKNOWN: "Readiness could not be determined",
}


def rule_for(name: Optional[str]) -> dict:
    """Return the named rule, falling back to the default with a warning."""
    key = (name or "strict_zero").strip() or "strict_zero"
    entry = config.READINESS_RULES.get(key)
    if entry is None:
        fallback = dict(config.READINESS_RULES["strict_zero"])
        fallback["requested"] = key
        fallback["note"] = ("Unknown readiness rule %r; using the strict rule. "
                            "Set DIAG_READINESS_RULE to one of: %s"
                            % (key, ", ".join(sorted(config.READINESS_RULES))))
        return fallback
    result = dict(entry)
    result["requested"] = key
    return result


def _incomplete(monitor: Dict) -> bool:
    return monitor.get("available") is True and monitor.get("complete") is False


def evaluate_readiness(
    monitor_status: Optional[dict],
    dtc_summary: Optional[dict] = None,
    rule_name: Optional[str] = None,
) -> dict:
    """Compute the readiness verdict from the four inputs.

    ``monitor_status`` is the output of :func:`decoders.monitor_status`;
    ``dtc_summary`` is the output of :func:`decoders.summarize_codes`. Either
    may be ``None`` (that query did not run), which degrades the verdict to
    ``unknown`` rather than assuming the good case - an unread monitor state
    must never be rendered as "ready".
    """
    rule = rule_for(rule_name)
    result = {
        "verdict": VERDICT_UNKNOWN,
        "headline": HEADLINES[VERDICT_UNKNOWN],
        "rule": rule,
        "disclaimer": config.READINESS_DISCLAIMER,
        "mil_on": None,
        "dtc_count_reported": None,
        "incomplete": [],
        "counted_incomplete": [],
        "exempt_incomplete": [],
        "not_supported": [],
        "allowance": rule.get("allow_incomplete", 0),
        "reasons": [],
        "inputs_missing": [],
    }

    if not monitor_status or not monitor_status.get("ok"):
        result["inputs_missing"].append("monitor status (01 01)")
        result["reasons"].append(
            "Mode 01 PID 01 was not available: %s"
            % ((monitor_status or {}).get("error") or "no data"))
        return result

    mil_on = bool(monitor_status.get("mil_on"))
    reported_count = monitor_status.get("dtc_count")
    result["mil_on"] = mil_on
    result["dtc_count_reported"] = reported_count
    result["engine_type"] = monitor_status.get("engine_type")

    monitors: List[dict] = list(monitor_status.get("common") or []) + \
        list(monitor_status.get("specific") or [])
    for monitor in monitors:
        if monitor.get("available") is True and monitor.get("complete") is False:
            result["incomplete"].append({
                "key": monitor.get("key"),
                "label": monitor.get("label"),
                "kind": monitor.get("kind"),
            })
        elif monitor.get("available") is False and monitor.get("state") != "reserved":
            result["not_supported"].append({
                "key": monitor.get("key"),
                "label": monitor.get("label"),
            })

    exempt = set(rule.get("exempt") or ())
    for item in result["incomplete"]:
        if item["key"] in exempt:
            result["exempt_incomplete"].append(item)
        else:
            result["counted_incomplete"].append(item)

    allowance = int(rule.get("allow_incomplete", 0) or 0)
    counted = len(result["counted_incomplete"])
    result["counted_count"] = counted

    # --- codes (input 2 and 4) --------------------------------------------
    codes_total = None
    if dtc_summary is not None:
        codes_total = int(dtc_summary.get("total", 0))
        result["codes"] = {
            "stored": len(dtc_summary.get("stored") or []),
            "pending": len(dtc_summary.get("pending") or []),
            "permanent": len(dtc_summary.get("permanent") or []),
            "total": codes_total,
        }
    else:
        result["inputs_missing"].append("DTC lists (03 / 07 / 0A)")
        result["codes"] = None

    # --- verdict ----------------------------------------------------------
    if mil_on:
        result["verdict"] = VERDICT_MIL_ON
        result["reasons"].append("Mode 01 PID 01 reports the warning light is on")
    elif codes_total:
        result["verdict"] = VERDICT_CODES_PRESENT
        result["reasons"].append("%d fault code(s) present" % codes_total)
    elif reported_count:
        # Byte A counts confirmed codes; if Mode 03 came back empty but the
        # counter disagrees, believe the counter and say so.
        result["verdict"] = VERDICT_CODES_PRESENT
        result["reasons"].append(
            "PID 01 reports %d stored code(s) even though Mode 03 returned none"
            % reported_count)
    elif counted > allowance:
        result["verdict"] = VERDICT_NOT_READY
        result["reasons"].append(
            "%d supported monitor(s) incomplete, rule allows %d"
            % (counted, allowance))
        for item in result["counted_incomplete"]:
            result["reasons"].append("incomplete: %s" % item["label"])
    elif codes_total is None:
        result["verdict"] = VERDICT_UNKNOWN
        result["reasons"].append("readiness not evaluated: DTC lists were not read")
    else:
        result["verdict"] = VERDICT_READY
        if allowance:
            result["reasons"].append(
                "all supported monitors complete (%d spare incomplete slot(s))"
                % (allowance - counted))
        else:
            result["reasons"].append("all supported monitors complete")

    if result["exempt_incomplete"]:
        result["reasons"].append(
            "incomplete but exempt under this rule: %s"
            % ", ".join(item["label"] for item in result["exempt_incomplete"]))
    if result["not_supported"]:
        result["reasons"].append(
            "not supported on this vehicle (ignored): %s"
            % ", ".join(item["label"] for item in result["not_supported"]))

    result["headline"] = HEADLINES[result["verdict"]]
    return result


def explain(result: dict) -> Sequence[str]:
    """Return the human-readable reasons of a verdict, headline first."""
    lines = [result.get("headline", "")]
    lines.extend(result.get("reasons") or [])
    if result.get("disclaimer"):
        lines.append(result["disclaimer"])
    return lines
