"""The scan engine: runtime discovery, then everything else in order.

Order is not cosmetic. Discovery first means every later step is gated by what
the car actually supports (docs/V1_SPEC.md: "features keyed off support bits,
never assumed"), which is also what makes the app universal - there is no
vehicle-specific list anywhere in this file. Then faults, then MIL/readiness,
then Mode 06, then identity. Live values come last because they are the only
part a user would not miss if the ECU went away mid-scan.

Discipline the engine inherits from :class:`~backend.diag.lane.DiagLink`:
single flight, <=15 s per query, one retry, and a full stop on the first
timeout (a timeout is a real fault signal - aborting keeps the partial result
honest and stops us from hammering a dead ObdManager).

The engine emits an event per step, so ``GET /diag/scan/stream`` can show
partials while the scan is still running, and it keeps the full event list so a
client that subscribes late still receives everything (partials are never
discarded). Everything it returns is plain JSON-serialisable data.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from . import config, decoders, names, verdict
from . import vin as vin_util
from .lane import STATE_SCANNING, DiagLink, HostAdapter, QueryResult

#: Fault-query command -> report key.
_CODE_KEYS = {"03": "stored", "07": "pending", "0A": "permanent"}

#: Support-bitmap probes. Each one answers "which of the next 32 ids exist".
DISCOVERY_COMMANDS: Sequence[tuple] = (
    ("0100", "Supported PIDs 01-20"),
    ("0120", "Supported PIDs 21-40"),
    ("0140", "Supported PIDs 41-60"),
    ("0160", "Supported PIDs 61-80"),
    ("0600", "Supported OBDMIDs (Mode 06)"),
    ("0620", "Supported OBDMIDs 21-40 (Mode 06)"),
    ("0900", "Supported info types (Mode 09)"),
    ("0200", "Freeze-frame support (Mode 02)"),
)

#: Fault queries. ``0A`` (permanent codes) is a negative fixture: on this ECU it
#: returns NO DATA, and that is a *correct* answer, not a failure.
FAULT_COMMANDS: Sequence[tuple] = (
    ("03", "Stored DTCs"),
    ("07", "Pending DTCs"),
    ("0A", "Permanent DTCs (may be unsupported)"),
    ("0102", "Freeze-frame DTC that triggered storage"),
)

#: MIL + readiness, the inspection pair.
READINESS_COMMANDS: Sequence[tuple] = (
    ("0101", "Monitor status since DTCs cleared"),
    ("0141", "Monitor status this drive cycle"),
)

#: Live PIDs worth reading on a diesel, in display order. Only supported ones
#: are ever queried; anything missing is reported as unsupported, not as an
#: error. This is a *reading list*, not a capability claim.
LIVE_PIDS: Sequence[int] = (
    0x04, 0x05, 0x0B, 0x0C, 0x0F, 0x10, 0x11, 0x1C, 0x1F, 0x21, 0x23, 0x2F,
    0x30, 0x31, 0x33, 0x3C, 0x42, 0x51, 0x5C,
)

#: Identity, in the order a human wants to see it. 0904/0906 are multi-frame
#: and are attempted once, guarded (V1_SPEC: "0904/0906 guarded").
IDENTITY_COMMANDS: Sequence[tuple] = (
    ("0902", "VIN", False),
    ("090A", "ECU name", False),
    ("0904", "Calibration ID (guarded, multi-frame)", True),
    ("0906", "Calibration verification numbers (guarded, multi-frame)", True),
)


class ScanEngine:
    """Runs one scan over a :class:`DiagLink` and returns a report dict."""

    def __init__(
        self,
        link: DiagLink,
        cfg: Optional[config.Config] = None,
        db=None,
        on_event: Optional[Callable[[dict], None]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.link = link
        self.cfg = cfg or link.cfg
        self.db = db
        self.clock = clock
        self._listeners: List[Callable[[dict], None]] = []
        if on_event is not None:
            self._listeners.append(on_event)
        self.events: List[dict] = []
        self.steps: List[dict] = []
        self.lock = threading.Lock()
        self.scan_id: Optional[str] = None
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.abort_reason: Optional[str] = None
        self.running = False
        self.report: Optional[dict] = None
        self.resolved_mode: Optional[str] = None
        self._vin: Optional[str] = None

    # --- event plumbing ------------------------------------------------------
    def subscribe(self, listener: Callable[[dict], None]) -> Callable[[], None]:
        """Attach a listener; it immediately receives the backlog."""
        with self.lock:
            backlog = list(self.events)
            self._listeners.append(listener)

        for event in backlog:
            try:
                listener(event)
            except Exception:  # pragma: no cover - a dead listener must not kill a scan
                pass

        def unsubscribe() -> None:
            with self.lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _emit(self, event: dict) -> None:
        event = dict(event)
        event.setdefault("at", self.clock())
        if self.scan_id:
            event.setdefault("scan_id", self.scan_id)
        with self.lock:
            self.events.append(event)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # pragma: no cover
                pass

    # --- one query, recorded ------------------------------------------------
    def ask(self, command: str, label: str, timeout: Optional[float] = None,
            retries: Optional[int] = None) -> QueryResult:
        result = self.link.query(command, timeout=timeout, retries=retries)
        step = result.to_dict()
        step.update({"label": label, "at": self.clock()})
        self.steps.append(step)
        self._emit({"type": "step", "step": step})
        return result

    def _should_abort(self, result: QueryResult) -> bool:
        if self.abort_reason:
            return True
        if result.error and "timeout" in result.error:
            self.abort_reason = (
                "%s timed out (%s); scan stopped on first timeout to keep the "
                "partial result honest" % (result.command, result.error))
            self._emit({"type": "abort", "reason": self.abort_reason})
            return True
        return False

    # --- the scan ------------------------------------------------------------
    def run(self, discovered_note: str = "") -> dict:
        if self.running:
            raise RuntimeError("scan already running")
        self.running = True
        self.scan_id = uuid.uuid4().hex[:12]
        self.started_at = self.clock()
        self.abort_reason = None
        self.steps = []
        self.events = []
        self.link.reset_abort()
        self.link.set_state(STATE_SCANNING, "scan %s" % self.scan_id)
        self._emit({"type": "scan_started", "scan_id": self.scan_id,
                    "note": discovered_note})
        try:
            report = self._run_steps()
        finally:
            self.running = False
            self.link.set_state("idle", "scan finished")
        self.finished_at = self.clock()
        report["scan"].update({
            "finished_at": self.finished_at,
            "duration_s": round(self.finished_at - self.started_at, 2),
            "aborted": bool(self.abort_reason),
            "abort_reason": self.abort_reason,
        })
        self.report = report
        self._emit({"type": "scan_finished", "report": report})
        return report

    def _deadline(self) -> Optional[float]:
        if self.cfg.scan_deadline_s <= 0:
            return None
        started = self.started_at if self.started_at is not None else self.clock()
        return started + self.cfg.scan_deadline_s

    def _expired(self) -> bool:
        deadline = self._deadline()
        if deadline is None:
            return False
        if self.clock() > deadline:
            self.abort_reason = "scan deadline (%.0fs) exceeded" % self.cfg.scan_deadline_s
            self._emit({"type": "abort", "reason": self.abort_reason})
            return True
        return False

    def _run_steps(self) -> dict:
        scan_meta: Dict[str, object] = {
            "id": self.scan_id,
            "started_at": self.started_at,
            "host": getattr(self.link.host, "name", "unknown"),
            "mode": self.resolved_mode or self.cfg.normalized_mode(),
            "spacing_s": self.cfg.query_spacing_s,
            "timeout_s": self.cfg.query_timeout_s,
        }
        report: Dict[str, object] = {
            "scan": scan_meta,
            "notes": [],
            "disclaimer": config.READINESS_DISCLAIMER,
        }
        notes: List[str] = report["notes"]  # type: ignore[assignment]

        # 1. discovery ---------------------------------------------------------
        support = {"pids": {}, "obdmid": {}, "infotypes": [], "freeze_frame": None,
                   "bitmaps": {}}
        supported_pids: set = set()
        for command, label in DISCOVERY_COMMANDS:
            if self._expired():
                break
            result = self.ask(command, label)
            if self._should_abort(result) or self._expired():
                break
            decoded = result.decoded
            entry = {}
            if command.startswith("01"):
                data = decoders.supported_pids(decoded)
                entry = data
                if data.get("ok"):
                    base = int(command[2:], 16)
                    support["bitmaps"][command] = data.get("bitmap_hex")
                    for pid in data.get("pids") or []:
                        supported_pids.add(pid)
                    support["pids"]["01%02X" % base] = data.get("pids") or []
            elif command.startswith("06"):
                data = decoders.monitor_test_bitmap(decoded)
                entry = data
                if data.get("ok"):
                    base = int(command[2:], 16)
                    support["bitmaps"][command] = data.get("bitmap_hex")
                    support["obdmid"]["06%02X" % base] = data.get("obdmids") or []
            elif command.startswith("09"):
                data = decoders.info_types(decoded)
                entry = data
                support["infotypes"] = data.get("infotypes") or []
            elif command.startswith("02"):
                data = {"raw": decoded.payload.hex().upper(),
                        "supported_hint": decoded.status}
                entry = data
                support["freeze_frame"] = bool(decoded.payload)
            report.setdefault("discovery", {})[command] = {  # type: ignore[arg-type]
                "label": label,
                "status": decoded.status,
                "decoded": entry,
            }
        report["support"] = support
        self._emit({"type": "phase", "phase": "discovery_done",
                    "supported_pids": sorted(supported_pids)})

        # 2. faults ------------------------------------------------------------
        codes = {"stored": [], "pending": [], "permanent": [], "mil": None,
                 "dtc_count": None, "freeze_frame_dtc": None, "queries": {}}
        for command, label in FAULT_COMMANDS:
            if self._expired():
                break
            result = self.ask(command, label)
            if self._should_abort(result) or self._expired():
                break
            decoded = result.decoded
            if command == "0102":
                codes["freeze_frame_dtc"] = decoders.freeze_frame_dtc(decoded)
                continue
            data = decoders.dtc_list(decoded, mode=int(command, 16))
            key = _CODE_KEYS.get(command) or command
            codes[key] = data.get("codes") or []
            codes["queries"][command] = {"status": decoded.status,
                                         "supported": data.get("ok"),
                                         "note": data.get("note")}
            if decoded.status in ("no_data", "empty"):
                notes.append("%s (%s): the ECU does not support this query - "
                             "recorded as a negative result, not a fault."
                             % (command, label))
        report["codes"] = codes

        # 3. MIL + readiness ---------------------------------------------------
        monitor = None
        cycle_monitor = None
        for command, label in READINESS_COMMANDS:
            if self._expired():
                break
            result = self.ask(command, label)
            if self._should_abort(result) or self._expired():
                break
            data = decoders.monitor_status(result.decoded)
            if command == "0101":
                monitor = data
            else:
                cycle_monitor = data
        if monitor and monitor.get("ok"):
            codes["mil"] = monitor.get("mil_on")
            codes["dtc_count"] = monitor.get("dtc_count")
        report["monitors"] = {"since_clear": monitor, "this_cycle": cycle_monitor}

        # 4. Mode 06 ----------------------------------------------------------
        report["monitor_tests"] = self._mode06(support, notes)

        # 5. identity ---------------------------------------------------------
        identity = {}
        for command, label, guarded in IDENTITY_COMMANDS:
            if self._expired():
                break
            # 0904/0906 are multi-frame and are attempted once without a
            # retry ("guarded" in V1_SPEC): a second multi-frame read is the
            # cheapest way to starve the served client.
            result = self.ask(command, label,
                              timeout=self.cfg.query_timeout_s,
                              retries=0 if guarded else None)
            if self._should_abort(result) or self._expired():
                break
            data = decoders.vehicle_info(result.decoded)
            data["guarded"] = guarded
            data["status"] = result.decoded.status
            identity[command] = data
        report["identity"] = identity

        # 6. live values ------------------------------------------------------
        live = []
        for pid in LIVE_PIDS:
            if pid not in supported_pids:
                continue
            if self._expired():
                break
            command = "01%02X" % pid
            result = self.ask(command, names.pid_name(pid))
            if self._should_abort(result) or self._expired():
                break
            live.append(decoders.pid_value(result.decoded))
        report["live"] = live

        # 7. verdict + code enrichment ----------------------------------------
        summary = decoders.summarize_codes([codes["stored"], codes["pending"],
                                            codes["permanent"]])
        codes["summary"] = summary
        self._vin = _identity_text(identity, "0902")
        enriched = self._enrich_codes(codes, identity)
        report["codes"] = enriched
        readiness = verdict.evaluate_readiness(
            monitor, summary, rule_name=self.cfg.readiness_rule)
        readiness["explain"] = list(verdict.explain(readiness))
        readiness["this_cycle"] = cycle_monitor
        report["readiness"] = readiness

        vehicle = self._vehicle(identity, supported_pids, live)
        report["vehicle"] = vehicle

        scan_meta.update({
            "step_log": list(self.steps),
            "queries": self.link.queries,
            "timeouts": self.link.timeouts,
            "retries": self.link.retries,
            "failures": self.link.failures,
            "supported_pid_count": len(supported_pids),
            "supported_obdmid_count": sum(len(v) for v in support["obdmid"].values()),
            "steps": len(self.steps),
        })
        return report

    # --- Mode 06 -------------------------------------------------------------
    def _mode06(self, support: dict, notes: List[str]) -> List[dict]:
        """Query every OBDMID that is either advertised or probe-worthy.

        The advertised bitmap is authoritative for *support* but not for *what
        was captured*: this ECU under-reports in ``0600`` (0x31/0x85 answered in
        Phase 1 although their bits are clear - docs/DECODED_FIXTURES.md). So the
        candidate set is advertised MIDs UNION the probe order, capped.
        """
        advertised: List[int] = []
        for key, ids in (support.get("obdmid") or {}).items():
            advertised.extend(ids or [])
        candidates: List[int] = []
        probe_order = list(getattr(self.cfg, "mode06_candidates", ()) or ())
        for mid in list(advertised) + [m for m in probe_order if m not in advertised]:
            if mid == 0x00 or mid in candidates:
                continue
            candidates.append(mid)
        cap = max(0, int(getattr(self.cfg, "mode06_max_mids", 0) or 0))
        if cap and len(candidates) > cap:
            notes.append("Mode 06: %d candidate OBDMIDs, capped to %d "
                         "(raise DIAG_MODE06_MAX_MIDS to read more)."
                         % (len(candidates), cap))
            candidates = candidates[:cap]

        results: List[dict] = []
        for mid in candidates:
            if self._expired():
                break
            command = "06%02X" % mid
            result = self.ask(command, names.obdmid_name(mid))
            if self._should_abort(result) or self._expired():
                break
            data = decoders.monitor_tests(result.decoded, obdmid=mid)
            data["advertised"] = mid in advertised
            entries = []
            for entry in data.get("tests") or []:
                entry = dict(entry)
                if entry.get("within_limits") is False:
                    entry["judgement"] = "outside-limits"
                elif entry.get("within_limits") is True:
                    entry["judgement"] = "within-limits"
                else:
                    entry["judgement"] = "unknown"
                entries.append(entry)
            data["tests"] = entries
            failed = [e for e in entries if e.get("judgement") == "outside-limits"]
            data["summary"] = {
                "tests": len(entries),
                "outside_limits": len(failed),
                "ambiguous": bool(data.get("layout_ambiguous")),
                "ambiguous_note": data.get("parse_note") or "",
                "residual_hex": data.get("residual_hex") or "",
            }
            results.append(data)
        return results

    # --- code enrichment ----------------------------------------------------
    def _enrich_codes(self, codes: dict, identity: dict) -> dict:
        if self.db is None:
            for key in ("stored", "pending", "permanent"):
                for code in codes.get(key) or []:
                    code.setdefault("lookup", {"available": False,
                                               "reason": "no DTC database loaded"})
            return codes
        maker = (self.cfg.dtc_default_maker
                 or vin_util.maker_from_vin(self._vin)
                 or None)
        for key in ("stored", "pending", "permanent"):
            for code in codes.get(key) or []:
                try:
                    code["lookup"] = self.db.lookup(code.get("code", ""), maker=maker)
                except Exception as exc:  # pragma: no cover - defensive
                    code["lookup"] = {"available": False, "reason": str(exc)}
        return codes

    # --- vehicle block ------------------------------------------------------
    def _vehicle(self, identity: dict, supported_pids: set,
                 live: Optional[Sequence[dict]] = None) -> dict:
        vin = _identity_text(identity, "0902")
        calid = _identity_text(identity, "0904")
        cvn = (identity.get("0906") or {}).get("value")
        ecu_name = _identity_text(identity, "090A")
        # PID 0x1C is a *live* reading, not a Mode 09 reply: look for it in the
        # live block first (identity never holds it) and fall back to whatever
        # the identity dict happens to carry.
        decoded_live = next((entry for entry in (live or [])
                             if entry.get("pid") == 0x1C), None)
        if decoded_live is None:
            decoded_live = identity.get("01%02X" % 0x1C) or {}
        standard_code = decoded_live.get("raw")
        standard = {"code": standard_code,
                    "name": names.obd_standard_name(standard_code),
                    "raw_hex": decoded_live.get("raw_hex")}
        vin_info = vin_util.resolve(vin, maker_hint=self.cfg.dtc_default_maker,
                                    online_enabled=False)
        return {
            "vin": vin,
            "calid": calid,
            "cvn": cvn,
            "ecu_name": ecu_name,
            "obd_standard": standard,
            "raw_identity": identity,
            "pid_01C": decoded_live,
            "vin_17_chars": len(vin or "") == 17,
            "vin_info": vin_info,
            "logs_available": {
                "stored_dtc_count": 0x01 in supported_pids,
            },
        }


def _identity_text(identity: dict, command: str) -> Optional[str]:
    """Pull the printable value of a Mode 09 response.

    ``decoders.vehicle_info`` puts the text under ``detail`` for the ASCII
    infotypes, so read the detail first and only then the flat value - reading
    ``ascii`` off the top level (as an earlier revision did) always came back
    empty, which is why the report had a null VIN even on a car that answers
    ``0902``.
    """
    entry = identity.get(command) or {}
    detail = entry.get("detail") or {}
    text = detail.get("ascii") or entry.get("value")
    if isinstance(text, str):
        text = text.strip()
    return text or None


def scan_to_events(report: dict) -> Iterable[dict]:
    """Split a finished report into the events a stream client would have seen.

    Used by the replay host so the frontend can develop against a canned scan
    without a car (and by tests, to prove streaming and polling agree).
    """
    yield {"type": "scan_started", "scan_id": report.get("scan", {}).get("id")}
    for step in report.get("scan", {}).get("step_log") or []:
        yield {"type": "step", "step": step}
    yield {"type": "scan_finished", "report": report}


def detect_mode(cfg: config.Config, probe=None) -> str:
    """Work out whether we must ride charts' served client or own the slot.

    Proxy mode is the default when a race-dash charts process is alive, because
    Hudiy serves OBD to exactly one process (ARCHITECTURE_NOTES.md, DEF
    CONSTRAINT). Standalone is only for installs where charts is absent.
    """
    if cfg.mode in (config.MODE_PROXY, config.MODE_STANDALONE):
        return cfg.mode
    checker = probe or _charts_alive
    return config.MODE_PROXY if checker(cfg) else config.MODE_STANDALONE


def _charts_alive(cfg: config.Config) -> bool:
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(cfg.charts_health_url,
                                    timeout=cfg.charts_probe_timeout_s) as response:
            body = json.loads(response.read(4096).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return bool(body.get("hudiy_connected", True))
