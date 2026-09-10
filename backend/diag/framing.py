"""Sequential parsing of OBD payloads as delivered by the Hudiy TCP API.

This module is the single place where raw bytes are turned into frames. It
exists because two Phase-1 incidents traced back to parsing:

* a regex over ``7E8\\d+:`` swallowed data digits and produced an infinite loop
  plus a gateway OOM (AGENTS.md section 3.4);
* multi-frame responses concatenate ``0:...1:...2:...`` with *variable* hex
  lengths, so slicing must be driven by the frame counter, not by fixed widths.

Rules implemented here, in order of importance:

1. **No regular expressions.** The frame scanner walks the string by hand.
2. **Counter-driven slicing.** For the ``N:`` form the next frame boundary is
   found by searching for the marker ``str(n + 1) + ":"`` starting at the end
   of frame ``n``'s body. Hex text can never contain ``:``, so a marker can
   only be a counter.
3. **Nothing is invented.** If the text does not fit a known shape the raw text
   is preserved and reported as unparsable instead of being guessed at.
4. ``NO DATA`` / empty strings are *valid negative answers*, surfaced as
   ``non_data`` rather than as errors (V1_SPEC rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

HEX_CHARS = frozenset("0123456789abcdefABCDEF")
WHITESPACE = frozenset(" \t\r\n")

#: Text an ELM327 / Hudiy can emit instead of (or alongside) data.
NON_DATA_TOKENS = (
    "NO DATA",
    "NODATA",
    "SEARCHING...",
    "SEARCHING",
    "UNABLE TO CONNECT",
    "BUS INIT",
    "STOPPED",
    "CAN ERROR",
    "ERROR",
    "?",
    ">",
)

#: Bytes an ECU may use to pad the tail of a CAN frame.
PAD_BYTES = (0xAA, 0x00, 0xFF, 0xCC)

STYLE_COUNTER = "counter"        # "0:4902015756571:5A5A5A31..."  (Hudiy/ELM form)
STYLE_BARE_HEX = "bare_hex"      # "4100983BA013"
STYLE_SPACED = "spaced_bytes"    # "41 00 98 3B A0 13"
STYLE_EMPTY = "empty"
STYLE_UNPARSABLE = "unparsable"


class FrameParseError(Exception):
    """Raised only for programmer errors; malformed input is reported, not raised."""


@dataclass
class ParsedPayload:
    """Result of parsing one Hudiy ``message.data`` list."""

    frames: List[str] = field(default_factory=list)
    style: str = STYLE_EMPTY
    non_data: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    raw_items: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when the ECU answered but had nothing to say (``NO DATA``)."""
        return not self.frames

    def hex_joined(self) -> str:
        return "".join(self.frames)

    def to_bytes(self) -> bytes:
        return frames_to_bytes(self.frames)

    @property
    def data(self) -> bytes:
        """The concatenated data bytes (empty when the ECU said nothing)."""
        return self.to_bytes()

    @property
    def text(self) -> str:
        """The payload as Hudiy delivered it, for reports and logs."""
        return " | ".join(self.raw_items) if self.raw_items else ""


#: Readability alias: the decode layer thinks in terms of "parsed frames".
ParsedFrames = ParsedPayload


def _strip_inner_whitespace(text: str) -> str:
    return "".join(ch for ch in text if ch not in WHITESPACE)


def _is_hex(text: str) -> bool:
    return bool(text) and all(ch in HEX_CHARS for ch in text)


def _looks_like_counter_start(text: str) -> Optional[int]:
    """Return the leading counter value when ``text`` starts with ``N:``."""
    index = 0
    digits: List[str] = []
    while index < len(text) and text[index].isdigit():
        digits.append(text[index])
        index += 1
    if not digits or index >= len(text) or text[index] != ":":
        return None
    # A counter is a small decimal line number, not a 9+ digit blob.
    if len(digits) > 3:
        return None
    return int("".join(digits))


def _find_marker(text: str, start: int, counter: int) -> int:
    """Index of the counter digits of the next ``"<counter>:"`` marker.

    The marker is glued to the previous frame's hex digits in the wire form
    (``...5756571:4A31...``), so the digits are looked up *backwards from the
    colon* rather than forwards from a boundary. Hex text cannot contain ``:``,
    so every colon is a frame separator - which also makes ``1:`` unambiguous
    when the counter is ``11``.
    """
    label = str(counter)
    length = len(label)
    index = text.find(":", start)
    while index != -1:
        begin = index - length
        if begin >= 0 and text[begin:index] == label:
            return begin
        index = text.find(":", index + 1)
    return -1


def _parse_counter_style(text: str) -> ParsedPayload:
    """Parse the ``0:<hex>1:<hex>2:<hex>`` form Hudiy delivers."""
    result = ParsedPayload(style=STYLE_COUNTER)
    counter = _looks_like_counter_start(text)
    if counter is None:
        result.style = STYLE_UNPARSABLE
        result.problems.append("counter-style text did not start with N:")
        return result

    position = len(str(counter)) + 1  # skip "<n>:"
    index = 0
    while position <= len(text):
        next_marker = _find_marker(text, position, counter + 1)
        if next_marker < position:
            body = text[position:]
            tail = True
        else:
            body = text[position:next_marker]
            tail = False
        body_no_ws = _strip_inner_whitespace(body)
        if body_no_ws:
            if _is_hex(body_no_ws):
                if len(body_no_ws) % 2:
                    result.problems.append(
                        "frame %d has an odd number of hex digits (%d)" % (counter, len(body_no_ws))
                    )
                else:
                    result.frames.append(body_no_ws.upper())
            else:
                result.non_data.append(body_no_ws)
        if tail:
            break
        position = next_marker + len(str(counter + 1)) + 1
        counter += 1
        index += 1
        if index > 256:  # sanity cap: no OBD response has 256 frames
            result.problems.append("frame counter exceeded 256; scan aborted")
            break
    return result


def _parse_flat(text: str) -> ParsedPayload:
    """Parse bare-hex / spaced-byte / non-data single-token text."""
    result = ParsedPayload(style=STYLE_UNPARSABLE)
    collapsed = _strip_inner_whitespace(text)

    if _is_hex(collapsed):
        result.style = STYLE_BARE_HEX
        if len(collapsed) % 2:
            result.problems.append("bare-hex text has an odd number of digits (%d)" % len(collapsed))
            return result
        result.frames.append(collapsed.upper())
        return result

    # Spaced byte groups: "41 00 98 3B A0 13" (each token 2 hex digits).
    tokens = text.split()
    if tokens and all(len(tok) == 2 and _is_hex(tok) for tok in tokens):
        result.style = STYLE_SPACED
        result.frames.append("".join(tokens).upper())
        return result

    # CAN-id prefixed lines ("7E8 06 41 00 98 3B A0 13"). The CAN id is 3 hex
    # digits (11-bit) or 8 hex digits (29-bit). Only accepted when the whole
    # line is otherwise uniform 2-digit tokens, so real data cannot be eaten.
    if tokens and len(tokens) >= 2 and all(len(tok) == 2 and _is_hex(tok) for tok in tokens[1:]):
        first = tokens[0]
        if (len(first) == 8 or (len(first) == 3 and first.upper().startswith("7"))) and _is_hex(first):
            result.style = STYLE_SPACED
            result.frames.append("".join(tokens[1:]).upper())
            result.problems.append("stripped CAN id header %s" % first.upper())
            return result

    upper = collapsed.upper()
    for token in NON_DATA_TOKENS:
        if upper.startswith(token.replace(" ", "")):
            result.style = STYLE_EMPTY
            result.non_data.append(text.strip())
            return result

    result.problems.append("text is neither hex data nor a known non-data token")
    result.non_data.append(text.strip())
    return result


def parse_item(item: object) -> ParsedPayload:
    """Parse one entry of ``message.data``."""
    if item is None:
        return ParsedPayload(style=STYLE_EMPTY)
    text = item if isinstance(item, str) else str(item)
    if not text.strip():
        # ``NO DATA`` arrives as an empty string through Hudiy - a valid
        # negative answer, not an error (V1_SPEC rule 3).
        return ParsedPayload(style=STYLE_EMPTY)
    if _looks_like_counter_start(text.lstrip()) is not None:
        return _parse_counter_style(text.lstrip())
    return _parse_flat(text)


def parse_payload(items: Optional[Iterable[object]]) -> ParsedPayload:
    """Parse a whole ``message.data`` sequence into a single frame list."""
    result = ParsedPayload()
    if items is None:
        return result
    if isinstance(items, (str, bytes)):
        items = [items]
    for item in items:
        if isinstance(item, (bytes, bytearray)):
            item = bytes(item).decode("ascii", "replace")
        result.raw_items.append(item if isinstance(item, str) else str(item))
        part = parse_item(item)
        result.frames.extend(part.frames)
        result.non_data.extend(part.non_data)
        result.problems.extend(part.problems)
        if part.style != STYLE_EMPTY:
            result.style = _merge_style(result.style, part.style)
    return result


#: Larger value wins; ``unparsable`` is the weakest (it describes a fragment,
#: and a resolvable sibling fragment is the more useful thing to report).
_STYLE_RANK = {
    STYLE_EMPTY: 0,
    STYLE_UNPARSABLE: 1,
    STYLE_BARE_HEX: 2,
    STYLE_SPACED: 3,
    STYLE_COUNTER: 4,
}


def _merge_style(current: str, incoming: str) -> str:
    return incoming if _STYLE_RANK.get(incoming, 0) > _STYLE_RANK.get(current, 0) else current


def frames_to_bytes(frames: Sequence[str]) -> bytes:
    """Concatenate frame hex strings into the raw payload bytes."""
    joined = "".join(frames)
    if not joined:
        return b""
    if len(joined) % 2:
        joined = joined[:-1]
    return bytes.fromhex(joined)


# ---------------------------------------------------------------------------
# ISO-TP (ISO 15765-2) reassembly - fallback only
# ---------------------------------------------------------------------------

def isotp_reassemble(data: bytes) -> Optional[bytes]:
    """Try to reassemble raw CAN frames that still carry ISO-TP PCI bytes.

    Hudiy's served client normally hands us *already reassembled* bytes (the
    ``0:``/``1:``/``2:`` form has the PCI stripped, see
    ``fixtures/capture_final_fixtures.jsonl``). Some Hudiy/ELM configurations
    deliver raw frames instead, so this function is offered as a *guarded*
    fallback:

    * single frame (PCI ``0x0N``): consumed only when ``N`` matches the
      remaining length exactly;
    * first frame (PCI ``0x1N``): consumed only when consecutive frames follow
      with valid ``0x2N`` PCI bytes and the declared length is satisfied.

    Returns ``None`` when the data is not valid ISO-TP, so callers never have a
    valid payload corrupted by a bad guess.
    """
    if len(data) < 2:
        return None
    pci = data[0]
    frame_type = pci >> 4

    if frame_type == 0x0:
        length = pci & 0x0F
        if length == 0 or length != len(data) - 1:
            return None
        return data[1:]

    if frame_type != 0x1:
        return None

    declared = ((pci & 0x0F) << 8) | data[1]
    if declared <= 0 or declared > 4095:
        return None
    body = bytearray()
    position = 2
    body.extend(data[position:position + 6])
    position += 6
    sequence = 1
    while len(body) < declared:
        if position >= len(data):
            return None
        cf_pci = data[position]
        if (cf_pci >> 4) != 0x2 or (cf_pci & 0x0F) != (sequence & 0x0F):
            return None
        body.extend(data[position + 1:position + 8])
        position += 8
        sequence += 1
        if sequence > 64:
            return None
    if len(body) < declared:
        return None
    return bytes(body[:declared])


def strip_tail_padding(data: bytes, pad_bytes: Sequence[int] = PAD_BYTES) -> bytes:
    """Drop ECU pad bytes from the tail of a payload.

    Mode 06 (``fixtures/round1_full_capture.json`` ``0685``) and Mode 09 CALID
    responses are padded to fill the last CAN frame. Only a trailing byte equal
    to a known pad value is removed, and never more than 7 of them, so real
    ``0xAA``/``0x00``/``0xFF`` data at the very end is preserved whenever it is
    followed by non-pad data.
    """
    end = len(data)
    removed = 0
    while end > 0 and removed < 7 and data[end - 1] in pad_bytes:
        end -= 1
        removed += 1
    return data[:end]


def split_chunks(data: bytes, size: int) -> Tuple[List[bytes], bytes]:
    """Split ``data`` into ``size``-byte chunks plus the remainder."""
    chunks = [data[offset:offset + size] for offset in range(0, len(data) - len(data) % size, size)]
    remainder = data[len(chunks) * size:]
    return chunks, remainder


def bytes_to_ascii(data: bytes) -> str:
    """ASCII-decode, mapping unprintable bytes to '.' (keeps length fidelity)."""
    return "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in data)


def bytes_to_hex(data: bytes) -> str:
    return data.hex().upper()
