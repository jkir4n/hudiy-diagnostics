#!/usr/bin/env python3
"""Build deterministic /scan mocks for the S11 clear-flow smoke test.

Reads the one real replay capture (/tmp/diag-scan.json) and derives:
- scan_codes.json  : same report, but 2 stored + 1 permanent code injected
                     (so the confirm screen has something to count), MIL on.
- scan_reread.json : post-clear state - no codes, two monitors Not ready
                     (so the auto re-read shows the all-incomplete wall).
Stdlib only. Run from the repo root.
"""
import copy
import json
import os

SRC = "/tmp/diag-scan.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "scan_codes.json")
OUT2 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "scan_reread.json")

STORED = [
    {"code": "P0301", "category": "Powertrain", "bytes": "0301",
     "known": True,
     "lookup": {"available": True, "found": True,
                "generic": {"description": "Cylinder 1 misfire detected"},
                "manufacturer_specific": None}},
    {"code": "P0401", "category": "Powertrain", "bytes": "0401",
     "known": True,
     "lookup": {"available": True, "found": True,
                "generic": {"description":
                            "Exhaust gas recirculation flow insufficient"},
                "manufacturer_specific": None}},
]
PERMANENT = [
    {"code": "P0420", "category": "Powertrain", "bytes": "0420",
     "known": True,
     "lookup": {"available": True, "found": True,
                "generic": {"description":
                            "Catalyst efficiency below threshold"},
                "manufacturer_specific": None}},
]


def main():
    with open(SRC, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["duration_s"] = 3.2
    payload["summary"] = "3 fault code(s), warning light on"

    with_codes = copy.deepcopy(payload)
    report = with_codes["report"]
    codes = report["codes"]
    codes["stored"] = copy.deepcopy(STORED)
    codes["pending"] = []
    codes["permanent"] = copy.deepcopy(PERMANENT)
    codes["mil"] = True
    codes["dtc_count"] = 2
    codes["summary"] = {"stored": ["P0301", "P0401"], "pending": [],
                        "permanent": ["P0420"], "total": 3, "clear": False}
    ready = report.get("readiness") or {}
    ready["verdict"] = "codes_present"
    ready["headline"] = "Fault codes stored"
    ready["mil_on"] = True
    report["readiness"] = ready
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(with_codes, handle)

    cleared = copy.deepcopy(payload)
    report2 = cleared["report"]
    codes2 = report2["codes"]
    codes2["stored"] = []
    codes2["pending"] = []
    codes2["permanent"] = []
    codes2["mil"] = False
    codes2["dtc_count"] = 0
    codes2["summary"] = {"stored": [], "pending": [], "permanent": [],
                         "total": 0, "clear": True}
    ready2 = report2.get("readiness") or {}
    ready2["verdict"] = "not_ready"
    ready2["headline"] = "Monitors not ready"
    ready2["incomplete"] = [
        {"key": "egr_vvt", "label": "EGR / VVT system"},
        {"key": "boost_pressure", "label": "Boost pressure"},
    ]
    ready2["counted_count"] = 2
    report2["readiness"] = ready2
    cleared["summary"] = "Monitor readiness incomplete - 0 code(s)"
    cleared["duration_s"] = 2.1
    with open(OUT2, "w", encoding="utf-8") as handle:
        json.dump(cleared, handle)
    print("wrote %s and %s" % (OUT, OUT2))

    # replay_clear.json: a ReplayHost command map for the LIVE /clear happy
    # path - the round-1 capture with a Mode 03 that holds one stored code
    # (P0401, the same bytes backend/tests/test_diag_clear.py uses) plus a
    # positive Mode 04 answer. Serve with:
    #   python3 -m backend.server --mode replay \
    #       --replay-fixtures smoke/replay_clear.json --port 44419
    round1_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "fixtures", "round1_full_capture.json")
    with open(round1_path, encoding="utf-8") as handle:
        cap = json.load(handle)
    cap["03"] = {"raw": ["43 01 04 01"]}
    cap["04"] = {"raw": ["44"]}
    out3 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "replay_clear.json")
    with open(out3, "w", encoding="utf-8") as handle:
        json.dump(cap, handle)
    print("wrote %s" % out3)


if __name__ == "__main__":
    main()
