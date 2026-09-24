"""Mode 04 (clear DTCs) interpretation and safety copy.

The *decision* to clear lives in :meth:`backend.server.DiagService.clear`,
which owns the confirm gate, the single-flight lock and the lane calls. This
module owns everything that must stay identical no matter who calls it:

* what a positive Mode 04 reply looks like (``0x44``, plus the ELM echo
  variants the research doc records),
* the negative shapes (``NO DATA``/empty silence, ``7F 04 <NRC>`` refusal),
* the user-facing copy (consequence list, fix-first guidance, permanent-code
  honesty note - docs/FEATURE_SURVEY_FINDINGS.md section 5,
  docs/OBD2_DIAGNOSTICS_RESEARCH.md section 7).

Nothing here knows any vehicle: Mode 04 framing is generic J1979 (request SID
``0x04``, response SID ``0x44`` = request + ``0x40``, no PID echo).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import decoders, framing, names, protocol

#: The Mode 04 request, normalised (``protocol.normalize_command`` accepts the
#: ``"04"`` / ``"04 "`` / ``"0x04"`` spellings; there is only one Mode 04).
MODE04_COMMAND = "04"

#: Expected response SID: request + 0x40, like every service 01-0A.
MODE04_RESPONSE_SID = 0x44

#: Outcome labels returned by :func:`interpret_mode04`.
OUTCOME_POSITIVE = "positive"
OUTCOME_NO_DATA = "no_data"
OUTCOME_NEGATIVE = "negative"
OUTCOME_UNRECOGNISED = "unrecognised"

#: Follow-up state for the UI's result screen (screen 2 of the survey's
#: two-screen flow): after any successful clear the monitors are incomplete
#: until a full drive cycle re-runs them.
FOLLOWUP = {"readiness": "incomplete",
            "message": "monitors reset; drive cycle needed"}

#: What the acknowledge step must convey (FEATURE_SURVEY_FINDINGS.md section 5,
#: OBDAD pattern). The backend 400 message names this list; the UI renders it.
CONSEQUENCE_LIST = (
    "clearing erases the stored codes AND the freeze-frame data AND the "
    "readiness monitors AND the Mode 06 test results; learned adaptations "
    "may also reset, so the car may run roughly during re-learn; readiness "
    "monitors reset to incomplete, so the car cannot pass an emissions "
    "inspection until a full drive cycle re-runs them"
)

#: The message a missing-confirm request gets. It names the consequence-list
#: requirement so a bypassed UI still cannot claim ignorance.
CONFIRM_REQUIRED_MESSAGE = (
    "clear refused: re-send with confirm=yes after showing the consequence "
    "list (%s) and confirming the fault was fixed first "
    "(unfixed codes come straight back). "
    "This gate is the safety boundary - the UI cannot bypass it."
    % CONSEQUENCE_LIST
)

#: Permanent-code honesty note (FEATURE_SURVEY_FINDINGS.md section 5, backed
#: by OBD2_DIAGNOSTICS_RESEARCH.md section 7.1). Rendered by the UI next to
#: every clear outcome. It states what no tool can do - it never advises a
#: battery disconnect (which the survey explicitly forbids suggesting).
PERMANENT_CODES_NOTE = (
    "Permanent codes (Mode 0A) cannot be cleared by any tool - not by this "
    "clear and not by disconnecting the battery. The ECU clears them itself "
    "only after the fault is fixed and its monitors pass."
)


def interpret_mode04(raw_items) -> Dict[str, object]:
    """Classify one Mode 04 reply.

    Returns ``{"outcome", "decoded", "note"}`` where outcome is one of
    ``positive`` / ``no_data`` / ``negative`` / ``unrecognised``.

    * ``positive`` - the ECU confirmed the clear (``0x44``, including the ELM
      echo variants below).
    * ``no_data`` - silence / ``NO DATA`` / empty string: over a functional
      CAN request an ECU that does not support the service stays silent
      (research doc section 2), so this is a *valid negative answer*.
    * ``negative`` - ``7F 04 <NRC>``: the ECU actively refused.
    * ``unrecognised`` - bytes that correlate with neither (stale echo,
      truncation, transport noise): never treated as success.

    ELM echo variants: with echo on (``ATE1``) the reply can arrive with the
    request bytes still glued in front (``04 44``). A leading echo of the
    exact request is stripped *sequentially* (never regex - AGENTS.md) and the
    remainder re-correlated; anything else is left untouched.
    """
    parsed = framing.parse_payload(raw_items)
    decoded = protocol.decode(MODE04_COMMAND, parsed)
    if decoded.ok and decoded.sid == MODE04_RESPONSE_SID:
        return {"outcome": OUTCOME_POSITIVE, "decoded": decoded, "note": None}

    # Echo variant: the data starts with the request itself, then the answer.
    data = parsed.data
    request = bytes.fromhex(MODE04_COMMAND)
    if len(data) > len(request) and data[:len(request)] == request \
            and data[len(request):len(request) + 1] == bytes((MODE04_RESPONSE_SID,)):
        remainder = data[len(request):]
        echo_decoded = protocol.decode_raw_items(
            MODE04_COMMAND, [remainder.hex().upper()])
        if echo_decoded.ok and echo_decoded.sid == MODE04_RESPONSE_SID:
            return {"outcome": OUTCOME_POSITIVE, "decoded": echo_decoded,
                    "note": "request echo stripped (ELM echo was on)"}

    if decoded.status in (protocol.STATUS_NO_DATA, "empty"):
        return {"outcome": OUTCOME_NO_DATA, "decoded": decoded, "note": None}
    if decoded.status == protocol.STATUS_NEGATIVE:
        return {"outcome": OUTCOME_NEGATIVE, "decoded": decoded, "note": None}
    return {"outcome": OUTCOME_UNRECOGNISED, "decoded": decoded, "note": None}


def count_stored_codes(decoded: protocol.DecodedResponse) -> int:
    """Number of stored DTCs in a Mode 03 reply (0 when unreadable).

    ``codes_seen_before`` is informational - the UI may warn on a zero-code
    clear, but clearing with no codes is still legal - so an undecodable
    pre-read degrades to 0 rather than failing the clear.
    """
    try:
        data = decoders.dtc_list(decoded, mode=3)
    except Exception:
        return 0
    count = data.get("code_count")
    return int(count) if isinstance(count, int) else 0


def refusal_reason(nrc: Optional[int]) -> str:
    """Human sentence for a ``7F 04 <NRC>`` refusal (generic J1979)."""
    if nrc is None:
        return ("the ECU refused the clear; nothing was confirmed cleared - "
                "re-scan before driving.")
    return ("the ECU refused the clear (7F 04 %02X - %s); nothing was "
            "confirmed cleared - re-scan before driving."
            % (nrc, names.nrc_name(nrc)))


def unsupported_reason() -> str:
    """Human sentence for a silent (NO DATA) Mode 04 reply."""
    return ("the ECU gave no answer to the clear (NO DATA) - it may not "
            "support clearing over generic OBD; nothing was confirmed "
            "cleared - re-scan before driving.")


def unconfirmed_reason(detail: str) -> str:
    """Human sentence for a timeout / unrecognised Mode 04 reply."""
    return ("the clear was NOT confirmed (%s); stored codes were NOT "
            "confirmed cleared - re-scan before driving." % detail)
