"""Hudiy Diagnostics backend (Phase 2a, slice 1).

Pure-diagnostic OBD-II lane for a Hudiy head unit. Two deployment modes share
one codebase:

* **proxy mode** - loaded *inside* the Race Dash charts process, riding the one
  OBD client Hudiy serves (see ``docs/ARCHITECTURE_NOTES.md``). Loaded by
  ``diag.proxy.install()`` from a 3-line hook in ``charts.py``.
* **standalone mode** - ``python -m diag``, opens its own charts-pattern Hudiy
  client, only when the charts process is absent.

Hard rules this package obeys (AGENTS.md, V1_SPEC.md):

1. Purely diagnostic - no gauges, HUD, trip or logging.
2. Universal - zero vehicle-specific code. Vehicle capabilities are discovered
   at runtime (PID bitmap, OBDMID map, VIN). This car's data exists only in
   ``fixtures/`` and ``tests/``.
3. Never open a second OBD connection while the charts lane is live.
4. Never block the charts poller.
5. Multi-frame responses are parsed sequentially (frame-count prefix + slice),
   never with a regex over CAN ids.
6. ``NO DATA`` arrives as an empty string and is a valid negative answer.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
