"""Runtime configuration for the diagnostics lane.

Everything has a safe default so the lane starts with no configuration at all.
The only values that *must* differ per vehicle/installation are discovery
inputs (handled at runtime), never baked-in vehicle facts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip(), 0)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_dtc_db() -> Path:
    """Locate the bundled DTC database without importing anything heavy."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "third_party" / "dtc-database" / "dtc_codes.db",
        here.parent.parent / "third_party" / "dtc-database" / "dtc_codes.db",
        Path("/opt/hudiy-diag/third_party/dtc-database/dtc_codes.db"),
        Path("/opt/hudiy-obd-charts/third_party/dtc-database/dtc_codes.db"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _default_report_dir() -> Path:
    """Reports are runtime state, so they live next to the package, not in it."""
    here = Path(__file__).resolve().parent
    for base in (here.parent, here.parent.parent):
        if (base / "diag").is_dir() or base.name == "backend":
            return base / "var" / "reports"
    return Path("/tmp/hudiy-diag-reports")


#: Modes the lane can run in.
MODE_AUTO = "auto"
MODE_PROXY = "proxy"
MODE_STANDALONE = "standalone"
MODES = (MODE_AUTO, MODE_PROXY, MODE_STANDALONE)

#: Readiness rule presets. The inspection arithmetic is a *local* rule, not a
#: technical fact (docs/DIESEL_READINESS_FINDINGS.md section 2), so it lives in
#: a table with the strictest sensible default rather than being hard-coded.
#:
#: ``allow_incomplete``  - supported-but-incomplete monitors the local rule
#:                         tolerates while still calling the car ready.
#: ``exempt``            - monitors that do not count even when incomplete.
#: ``note``              - shown next to the verdict so the wording stays honest.
READINESS_RULES = {
    "strict_zero": {
        "label": "Strict - every supported monitor must be complete",
        "allow_incomplete": 0,
        "exempt": (),
        "note": "Requires all supported monitors complete; used by several "
                "European EOBD inspections.",
    },
    "eu_eobd": {
        "label": "EU EOBD - all supported monitors complete",
        "allow_incomplete": 0,
        "exempt": (),
        "note": "EOBD readiness is evaluated with no incomplete monitors.",
    },
    "us_2001_plus": {
        "label": "US 2001 and newer - up to one incomplete monitor",
        "allow_incomplete": 1,
        "exempt": (),
        "note": "Common US allowance; verify local requirements.",
    },
    "us_1996_2000": {
        "label": "US 1996-2000 - up to two incomplete monitors",
        "allow_incomplete": 2,
        "exempt": (),
        "note": "Older-vehicle allowance; verify local requirements.",
    },
    "ca_diesel_2007_plus": {
        "label": "California diesel 2007+ - PM filter and NMHC exempt",
        "allow_incomplete": 0,
        "exempt": ("pm_filter", "nmhc_catalyst"),
        "note": "California diesel rule (revised July 2023).",
    },
}

#: Printed with every verdict. The app never claims a car will pass.
READINESS_DISCLAIMER = (
    "Readiness rules differ by country and model year. This verdict applies the "
    "configured rule to what the ECU reported; it is not an inspection result."
)


@dataclass
class Config:
    """Effective configuration for one lane instance."""

    # --- HTTP surface (always our own listener on a free port) -------------
    http_host: str = field(default_factory=lambda: _env_str("DIAG_HTTP_HOST", "127.0.0.1"))
    http_port: int = field(default_factory=lambda: _env_int("DIAG_HTTP_PORT", 44414))
    sse_keepalive_s: float = field(default_factory=lambda: _env_float("DIAG_SSE_KEEPALIVE_S", 15.0))
    max_sse_clients: int = field(default_factory=lambda: _env_int("DIAG_MAX_SSE_CLIENTS", 8))

    # --- Hudiy / OBD ------------------------------------------------------
    mode: str = field(default_factory=lambda: _env_str("DIAG_MODE", MODE_AUTO))
    hudiy_host: str = field(default_factory=lambda: _env_str("HUDIY_HOST", "127.0.0.1"))
    hudiy_port: int = field(default_factory=lambda: _env_int("HUDIY_TCP_PORT", 44405))
    charts_health_url: str = field(
        default_factory=lambda: _env_str("DIAG_CHARTS_HEALTH_URL", "http://127.0.0.1:44411/health")
    )
    charts_probe_timeout_s: float = field(
        default_factory=lambda: _env_float("DIAG_CHARTS_PROBE_TIMEOUT_S", 2.0)
    )
    #: Proxy lane: where the charts process exposes its OBD bridge. The charts
    #: process is the ONE process Hudiy serves OBD to (ARCHITECTURE_NOTES.md,
    #: DEF CONSTRAINT), so our queries travel through this URL instead of
    #: opening a second Hudiy connection that would be silently starved.
    charts_bridge_url: str = field(
        default_factory=lambda: _env_str(
            "DIAG_CHARTS_BRIDGE_URL", "http://127.0.0.1:44412/diag/obd"
        )
    )
    #: Optional shared secret for the bridge. Both ends are loopback-only, so
    #: this is defence in depth, not an authentication boundary.
    bridge_token: str = field(default_factory=lambda: _env_str("DIAG_BRIDGE_TOKEN", ""))
    #: Every bridged query costs the charts poller its turn, so the bridged
    #: request budget is deliberately tighter than a local one.
    bridge_timeout_s: float = field(
        default_factory=lambda: _env_float("DIAG_BRIDGE_TIMEOUT_S", 15.0)
    )
    #: Where exported reports are written when a client asks for a file.
    report_dir: Path = field(
        default_factory=lambda: Path(_env_str("DIAG_REPORT_DIR", str(_default_report_dir())))
    )

    #: Per-query timeout. V1_SPEC caps it at 15 s.
    query_timeout_s: float = field(default_factory=lambda: _env_float("DIAG_QUERY_TIMEOUT_S", 15.0))
    #: ONE retry max (V1_SPEC). Set 0 to disable retries entirely.
    query_retries: int = field(default_factory=lambda: _env_int("DIAG_QUERY_RETRIES", 1))
    #: Idle spacing between consecutive diagnostic queries, leaving the ELM free
    #: for the charts poller. The charts poller uses 0.35 s (visible) per PID.
    query_spacing_s: float = field(default_factory=lambda: _env_float("DIAG_QUERY_SPACING_S", 0.45))
    request_code_base: int = field(default_factory=lambda: _env_int("DIAG_REQUEST_CODE_BASE", 500000))
    #: Hard ceiling on the whole scan so a wedged ECU cannot pin a thread.
    scan_deadline_s: float = field(default_factory=lambda: _env_float("DIAG_SCAN_DEADLINE_S", 300.0))

    # --- Stale-handle detection (AGENTS.md section 4a) ---------------------
    #: Mirror of charts' own 12 s staleness threshold.
    stale_age_s: float = field(default_factory=lambda: _env_float("DIAG_STALE_AGE_S", 12.0))
    #: Consecutive dropped queries before declaring the ECU unresponsive.
    stale_confirm: int = field(default_factory=lambda: _env_int("DIAG_STALE_CONFIRM", 2))
    #: Backoff schedule (seconds) for automatic retry while stale.
    reconnect_backoff_s: Tuple[float, ...] = field(
        default_factory=lambda: (2.0, 4.0, 8.0, 15.0, 30.0)
    )

    # --- Mode 06 discovery ------------------------------------------------
    #: Intra-range walk: query 0600, then 0620/0640/... while the range marker
    #: bit says another range exists (mirrors the PID 00/20/40 walk).
    mode06_walk_ranges: bool = field(
        default_factory=lambda: _env_bool("DIAG_MODE06_WALK_RANGES", True)
    )
    #: Candidate OBDMIDs probed for test data after the bitmap walk. The 0600
    #: bitmap under-reports on the reference ECU (fixtures/round1_full_capture),
    #: so observed answers - not the bitmap alone - decide support.
    mode06_candidates: Tuple[int, ...] = field(
        default_factory=lambda: (0x01, 0x21, 0x31, 0x41, 0x61, 0x81, 0x85, 0xA1, 0xB1)
    )
    mode06_max_mids: int = field(default_factory=lambda: _env_int("DIAG_MODE06_MAX_MIDS", 24))

    # --- Readiness verdict ------------------------------------------------
    #: Which entry of :data:`READINESS_RULES` the verdict engine applies.
    readiness_rule: str = field(
        default_factory=lambda: _env_str("DIAG_READINESS_RULE", "strict_zero")
    )

    # --- DTC / VIN --------------------------------------------------------
    dtc_db_path: Path = field(default_factory=lambda: Path(_env_str("DIAG_DTC_DB", str(_default_dtc_db()))))
    dtc_default_maker: str = field(default_factory=lambda: _env_str("DIAG_DTC_DEFAULT_MAKER", ""))
    dtc_lookup_enabled: bool = field(default_factory=lambda: _env_bool("DIAG_DTC_LOOKUP", True))
    dtc_locale: str = field(default_factory=lambda: _env_str("DIAG_DTC_LOCALE", "en"))
    vin_decode_enabled: bool = field(default_factory=lambda: _env_bool("DIAG_VIN_DECODE", True))
    vin_decode_url: str = field(
        default_factory=lambda: _env_str(
            "DIAG_VIN_DECODE_URL",
            "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json",
        )
    )
    vin_decode_timeout_s: float = field(
        default_factory=lambda: _env_float("DIAG_VIN_DECODE_TIMEOUT_S", 6.0)
    )

    # --- Logging ----------------------------------------------------------
    log_level: str = field(default_factory=lambda: _env_str("DIAG_LOG_LEVEL", "INFO"))

    def normalized_mode(self) -> str:
        mode = (self.mode or MODE_AUTO).lower()
        return mode if mode in MODES else MODE_AUTO

    def clamp_v1_limits(self) -> None:
        """Enforce the V1_SPEC hard limits regardless of environment."""
        if self.query_timeout_s > 15.0:
            self.query_timeout_s = 15.0
        if self.query_timeout_s <= 0:
            self.query_timeout_s = 15.0
        if self.query_retries < 0:
            self.query_retries = 0
        if self.query_retries > 1:
            self.query_retries = 1
        if self.query_spacing_s < 0:
            self.query_spacing_s = 0.0
        if self.mode06_max_mids < 1:
            self.mode06_max_mids = 1


def load_config() -> Config:
    cfg = Config()
    cfg.clamp_v1_limits()
    return cfg
