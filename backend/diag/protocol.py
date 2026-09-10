"""OBD-II response semantics: request/response correlation and framing.

``framing.py`` answers "what bytes did the car send". This module answers
"what *kind* of answer is that, for the question we asked". The distinction
matters because the ELM327/Hudiy pipeline can deliver four different things
for one request and only one of them is data:

1. a positive response   - ``41 00 ...`` for request ``01 00``
2. a negative response   - ``7F 01 11`` (service not supported)
3. an empty string       - "NO DATA" through Hudiy; a *valid negative answer*
                           (AGENTS.md hard constraint 3), never an error
4. nothing recognisable  - stale-buffer echo, partial line, transport noise

Case 4 is the dangerous one: a stale echo of a *previous* query is a perfectly
valid-looking response for a *different* PID. Every response is therefore
correlated against the exact request that produced it, and an unrecognised
leading byte is reported as ``mismatch`` with the raw bytes preserved rather
than being forced into a shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import framing
from . import names

#: Response SID = request SID + 0x40 for OBD services 01-0A.
RESPONSE_SID_OFFSET = 0x40

#: Services whose response carries a PID immediately after the SID.
SERVICES_WITH_PID = frozenset({0x01, 0x02, 0x06, 0x09})

STATUS_OK = "ok"
STATUS_NO_DATA = "no_data"
STATUS_NEGATIVE = "negative"
STATUS_MISMATCH = "mismatch"
STATUS_UNPARSABLE = "unparsable"
STATUS_SHORT = "short"


class CommandError(ValueError):
    """Raised for a malformed request string (never for a bad *response*)."""


def normalize_command(command: str) -> str:
    """Return ``command`` as uppercase hex without separators.

    Accepts the forms the tooling and docs use interchangeably: ``0100``,
    ``01 00``, ``0x0100``, ``01,00``. Anything else is rejected loudly - a
    silently mis-typed command is worse than a crash.
    """
    if not isinstance(command, str):
        raise CommandError("command must be a string, got %r" % (command,))
    text = command.strip().upper().replace("0X", "")
    for sep in (" ", ",", "-", ":", "\t"):
        text = text.replace(sep, "")
    if not text:
        raise CommandError("empty command")
    if len(text) % 2:
        raise CommandError("command %r has an odd number of hex digits" % command)
    try:
        int(text, 16)
    except ValueError:
        raise CommandError("command %r is not hex" % command)
    return text


def split_command(command: str) -> tuple:
    """Return ``(sid, pid, extra)`` as ints/None for a normalised command."""
    text = normalize_command(command)
    raw = bytes.fromhex(text)
    sid = raw[0]
    pid = raw[1] if len(raw) > 1 else None
    extra = raw[2] if len(raw) > 2 else None
    return sid, pid, extra


def expected_response_sid(command: str) -> Optional[int]:
    sid, _pid, _extra = split_command(command)
    if 0x01 <= sid <= 0x0A:
        return sid + RESPONSE_SID_OFFSET
    return None


@dataclass
class DecodedResponse:
    """A single command/response pair after correlation."""

    command: str
    status: str
    sid: Optional[int] = None          # response service id
    pid: Optional[int] = None          # echoed pid/infotype (when applicable)
    error: Optional[str] = None        # short machine-readable reason
    nrc: Optional[int] = None          # negative response code
    payload: bytes = b""               # data after SID [and pid]
    raw_labels: Sequence[str] = field(default_factory=tuple)
    raw_text: str = ""
    framing: str = "raw"               # "raw" | "isotp"
    notes: Sequence[str] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "status": self.status,
            "sid": self.sid,
            "pid": self.pid,
            "error": self.error,
            "nrc": self.nrc,
            "nrc_name": names.nrc_name(self.nrc) if self.nrc is not None else None,
            "payload_hex": self.payload.hex().upper(),
            "raw": self.raw_text,
            "framing": self.framing,
            "notes": list(self.notes),
        }


def _no_data(command: str, parsed: framing.ParsedFrames, reason: str) -> DecodedResponse:
    return DecodedResponse(
        command=command,
        status=STATUS_NO_DATA,
        error=reason,
        raw_text=parsed.text,
        raw_labels=tuple(parsed.non_data),
        notes=("empty answer is a valid negative result, not an error",),
    )


def decode(command: str, parsed: framing.ParsedFrames) -> DecodedResponse:
    """Correlate ``parsed`` (the answer) with ``command`` (the question)."""
    command = normalize_command(command)
    sid_req, pid_req, _extra = split_command(command)
    want = expected_response_sid(command)

    if parsed.style == framing.STYLE_UNPARSABLE:
        return DecodedResponse(
            command=command, status=STATUS_UNPARSABLE,
            error="unrecognised payload - kept raw, never guessed",
            raw_text=parsed.text, raw_labels=tuple(parsed.non_data),
        )

    data = parsed.data
    if not data:
        return _no_data(command, parsed, "no bytes returned")

    # ---- direct interpretation --------------------------------------------
    result = _interpret(command, data, sid_req, pid_req, want, framing_label="raw")
    if result.status == STATUS_OK:
        return result

    # ---- ISO-TP reassembly fallback ---------------------------------------
    # Only tried when the direct read did NOT already correlate, so a valid
    # answer can never be re-interpreted (and thus corrupted) by this path.
    reassembled = framing.isotp_reassemble(data)
    if reassembled is not None and reassembled != data:
        alt = _interpret(command, reassembled, sid_req, pid_req, want,
                         framing_label="isotp")
        if alt.status in (STATUS_OK, STATUS_NEGATIVE):
            alt.notes = tuple(alt.notes) + ("unwrapped ISO-TP frames",)
            alt.raw_text = parsed.text
            return alt

    result.raw_text = parsed.text
    return result


def _interpret(command, data, sid_req, pid_req, want, framing_label):
    first = data[0]

    if first == 0x7F:
        if len(data) < 3:
            return DecodedResponse(
                command=command, status=STATUS_SHORT, error="truncated negative response",
                payload=data, framing=framing_label,
            )
        return DecodedResponse(
            command=command, status=STATUS_NEGATIVE, sid=0x7F, nrc=data[2],
            error="ECU refused the request", payload=data,
            framing=framing_label,
            notes=(names.nrc_name(data[2]),),
        )

    if want is None:
        return DecodedResponse(
            command=command, status=STATUS_MISMATCH,
            error="unsupported request service 0x%02X" % sid_req,
            payload=data, framing=framing_label,
        )

    if first != want:
        return DecodedResponse(
            command=command, status=STATUS_MISMATCH,
            error="expected response 0x%02X, got 0x%02X" % (want, first),
            payload=data, framing=framing_label,
        )

    body = data[1:]
    pid = None
    if sid_req in SERVICES_WITH_PID:
        if not body:
            return DecodedResponse(
                command=command, status=STATUS_SHORT,
                error="response has no PID echo", payload=body,
                framing=framing_label,
            )
        pid = body[0]
        body = body[1:]
        if pid_req is not None and pid != pid_req:
            return DecodedResponse(
                command=command, status=STATUS_MISMATCH, sid=first, pid=pid,
                error="PID echo 0x%02X does not match request 0x%02X" % (pid, pid_req),
                payload=body, framing=framing_label,
            )

    return DecodedResponse(
        command=command, status=STATUS_OK, sid=first, pid=pid,
        payload=body, framing=framing_label,
    )


# --------------------------------------------------------------------------
# Convenience: one-shot decode of a raw capture (fixtures, tests, replay)
# --------------------------------------------------------------------------

def decode_raw_items(command: str, raw_items) -> DecodedResponse:
    """Decode a list of raw payload strings exactly as Hudiy would deliver."""
    return decode(command, framing.parse_payload(raw_items))
