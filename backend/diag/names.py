"""Human-readable names for OBD-II identifiers.

Every table here is vehicle-independent by design (the app is universal): an
unknown identifier always falls back to ``"<id> (unknown)"`` rather than being
dropped, so a car that reports something new is still shown, never hidden.

Sources (see docs/OBD2_DIAGNOSTICS_RESEARCH.md for the full citations):
  * SAE J1979 / Appendix D  - OBDMID, TID tables
  * SAE J1979 / Appendix E  - UAS ID (unit and scaling) table
  * SAE J1979 section 4.2.10 - PID 01 monitor status bits
  * ISO 15031-6 / J2012     - DTC categories
  * ISO 14229-1             - negative response codes
"""

# --------------------------------------------------------------------------
# Negative response codes (ISO 14229-1 / SAE J1979 section 4.4)
# --------------------------------------------------------------------------

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

#: Negative codes that mean "ask again later", not "car is broken".
NRC_TRANSIENT = frozenset({0x21, 0x78})

# --------------------------------------------------------------------------
# Mode 01 PIDs (subset that the diagnostics lane reads or surfaces)
# --------------------------------------------------------------------------

PID_NAMES = {
    0x00: "PIDs supported [01-20]",
    0x01: "Monitor status since DTCs cleared",
    0x02: "Freeze frame DTC",
    0x03: "Fuel system status",
    0x04: "Calculated engine load",
    0x05: "Engine coolant temperature",
    0x0A: "Fuel pressure",
    0x0B: "Intake manifold absolute pressure",
    0x0C: "Engine speed",
    0x0D: "Vehicle speed",
    0x0F: "Intake air temperature",
    0x10: "Mass air flow rate",
    0x11: "Throttle position",
    0x1C: "OBD standards this vehicle conforms to",
    0x1F: "Run time since engine start",
    0x20: "PIDs supported [21-40]",
    0x21: "Distance travelled with MIL on",
    0x2F: "Fuel tank level input",
    0x30: "Warm-ups since codes cleared",
    0x31: "Distance travelled since codes cleared",
    0x33: "Absolute barometric pressure",
    0x40: "PIDs supported [41-60]",
    0x41: "Monitor status this drive cycle",
    0x42: "Control module voltage",
    0x46: "Ambient air temperature",
    0x4D: "Time run with MIL on",
    0x4E: "Time since trouble codes cleared",
    0x51: "Fuel type",
    0x5C: "Engine oil temperature",
    0x60: "PIDs supported [61-80]",
    0x78: "Exhaust gas temperature bank 1",
    0x79: "Exhaust gas temperature bank 2",
    0x7A: "DPF 1 differential pressure",
    0x7B: "DPF 1",
    0x7C: "DPF 1 temperature",
}

#: PID ranges used for runtime capability discovery, in walk order.
PID_RANGE_STARTS = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0)

#: PIDs whose response needs scaling. Kept explicit so the UI never prints a
#: raw byte as if it were a physical value.
PID_SCALING = {
    0x04: ("%", 100.0 / 255.0, 0.0),
    0x05: ("degC", 1.0, -40.0),
    0x0B: ("kPa", 1.0, 0.0),
    0x0C: ("rpm", 0.25, 0.0),
    0x0D: ("km/h", 1.0, 0.0),
    0x0F: ("degC", 1.0, -40.0),
    0x10: ("g/s", 0.01, 0.0),
    0x11: ("%", 100.0 / 255.0, 0.0),
    0x1F: ("s", 1.0, 0.0),
    0x21: ("km", 1.0, 0.0),
    0x2F: ("%", 100.0 / 255.0, 0.0),
    0x30: ("count", 1.0, 0.0),
    0x31: ("km", 1.0, 0.0),
    0x33: ("kPa", 1.0, 0.0),
    0x42: ("V", 0.001, 0.0),
    0x46: ("degC", 1.0, -40.0),
    0x4D: ("min", 1.0, 0.0),
    0x4E: ("min", 1.0, 0.0),
    0x5C: ("degC", 1.0, -40.0),
    0x7C: ("degC", 0.1, -40.0),
}

# --------------------------------------------------------------------------
# Mode 06 - OBDMID (monitor) names
# J1979 Appendix D; the diesel-specific MIDs (0x41-0x8F, 0x90-0xBF) are the
# ones this car actually reports. Petrol MIDs are kept for universality.
# --------------------------------------------------------------------------

OBDMID_NAMES = {
    0x01: "O2 sensor monitor bank 1 - sensor 1",
    0x02: "O2 sensor monitor bank 1 - sensor 2",
    0x03: "O2 sensor monitor bank 2 - sensor 1",
    0x04: "O2 sensor monitor bank 2 - sensor 2",
    0x05: "O2 sensor monitor bank 3 - sensor 1",
    0x06: "O2 sensor monitor bank 3 - sensor 2",
    0x21: "Catalyst monitor bank 1",
    0x22: "Catalyst monitor bank 2",
    0x31: "EGR monitor bank 1",
    0x32: "EGR monitor bank 2",
    0x35: "VVT monitor bank 1",
    0x36: "VVT monitor bank 2",
    0x41: "O2 sensor heater monitor bank 1 sensor 1",
    0x42: "O2 sensor heater monitor bank 1 sensor 2",
    0x51: "Secondary air monitor bank 1",
    0x61: "Purge flow/EVAP monitor",
    0x71: "EVAP leak monitor",
    0x81: "Zero fuel calibration monitor (diesel)",
    0x82: "Fuel system monitor (diesel)",
    0x85: "Boost pressure control monitor (diesel)",
    0x86: "Charge air / intake throttle monitor (diesel)",
    0x87: "Exhaust gas recirculation cooler monitor (diesel)",
    0x88: "Exhaust gas sensor monitor (diesel)",
    0x89: "VVT / swirl flap monitor (diesel)",
    0x8A: "PM filter monitor (diesel)",
    0x8B: "NOx aftertreatment monitor (diesel)",
    0x8C: "NMHC catalyst monitor (diesel)",
    0x8D: "Misfire monitor (diesel)",
    0x90: "NOx absorber monitor (diesel)",
    0xA1: "Misfire cylinder 1 data",
    0xA2: "Misfire cylinder 1 / general data",
    0xA3: "Misfire cylinder 2 data",
    0xA4: "Misfire cylinder 3 data",
    0xA5: "Misfire cylinder 4 data",
    0xA6: "Misfire cylinder 5 data",
    0xA7: "Misfire cylinder 6 data",
    0xB1: "PM filter efficiency monitor (DPF)",
    0xB2: "PM trap / DPF efficiency monitor",
}

#: OBDMIDs worth probing even when the 0600 bitmap does not list them. The
#: reference car proves why: 0600 only claimed MID 0x01 and the 0x20 range
#: marker, yet 0x31 and 0x85 answered with real test data. Order matters -
#: cheapest and most informative first.
OBDMID_PROBE_ORDER = (0x01, 0x21, 0x31, 0x81, 0x85, 0x86, 0x88, 0x8A, 0x8B,
                      0x8C, 0x8D, 0x90, 0xB1, 0xB2, 0xA2, 0xA4, 0xA5)

# --------------------------------------------------------------------------
# Mode 06 - TID names. TIDs are monitor-specific; the table below covers the
# shared "generic" TIDs (J1979 Appendix D) plus the VW diesel TIDs observed
# on the reference car. Unknown TIDs are renamed "TID 0xNN (manufacturer)".
# --------------------------------------------------------------------------

TID_NAMES = {
    # generic, J1979 Appendix D table D-2
    0x01: "Test value",
    0x02: "Minimum limit",
    0x03: "Maximum limit",
    0x04: "Test ID",
    0x05: "Test result",
    0x06: "Test limit",
    0x07: "Test ID",
    0x08: "Test limit",
    0x09: "Test ID",
    0x0A: "Test limit",
    0x0B: "Test ID",
    0x0C: "Test limit",
    0x0D: "Test ID",
    0x0E: "Test limit",
    0x0F: "Test ID",
    0x10: "Test limit",
    0x11: "Test ID",
    0x12: "Test limit",
    # VW diesel TIDs observed on the reference ECU (raw evidence, fixtures/)
    0xC0: "Manufacturer test group 0xC0",
    0xC1: "Manufacturer test group 0xC1",
    0xC2: "Manufacturer test group 0xC2",
    0xC5: "Manufacturer test group 0xC5",
}

# --------------------------------------------------------------------------
# Mode 06 - UAS ID (unit and scaling identifier), J1979 Appendix E.
# ``scale``/``offset`` apply as value * scale + offset. ``signed`` marks the
# 16-bit value as two's complement. Unlisted IDs are reported as "unknown
# scaling" and their raw 16-bit values are shown unscaled - never guessed.
# --------------------------------------------------------------------------

UAS_IDS = {
    0x00: {"unit": "", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "no scaling"},
    0x01: {"unit": "", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "raw value"},
    0x02: {"unit": "V", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x03: {"unit": "V", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x04: {"unit": "mA", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x05: {"unit": "mA", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x06: {"unit": "s", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x07: {"unit": "s", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x08: {"unit": "g", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x09: {"unit": "g", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x0A: {"unit": "deg", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x0B: {"unit": "deg", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x0C: {"unit": "L/s", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x0D: {"unit": "L/s", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x0E: {"unit": "kPa", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x0F: {"unit": "kPa", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x10: {"unit": "Pa", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x11: {"unit": "Pa", "scale": 1.0, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x12: {"unit": "degC", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x13: {"unit": "degC", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x14: {"unit": "Nm", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x15: {"unit": "Nm", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x16: {"unit": "rpm", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x17: {"unit": "rpm", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x18: {"unit": "km/h", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x19: {"unit": "km/h", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x1A: {"unit": "m/s", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x1B: {"unit": "m/s", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x1C: {"unit": "%", "scale": 0.001, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x1D: {"unit": "%", "scale": 0.001, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x1E: {"unit": "count", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "unsigned 16-bit"},
    0x1F: {"unit": "count", "scale": 1.0, "offset": 0.0, "signed": True,
           "note": "signed 16-bit"},
    0x30: {"unit": "count", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "manufacturer scaling (unsigned)"},
    0x31: {"unit": "count", "scale": 1.0, "offset": 0.0, "signed": True,
           "note": "manufacturer scaling (signed)"},
    0x82: {"unit": "", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "manufacturer scaling 0x82 (VW: unsigned ratio)"},
    0xFC: {"unit": "", "scale": 1.0, "offset": 0.0, "signed": False,
           "note": "manufacturer scaling 0xFC (VW: unsigned ratio)"},
}


def pid_name(pid):
    return PID_NAMES.get(pid) or "PID 0x%02X (unknown)" % pid


def obdmid_name(mid):
    return OBDMID_NAMES.get(mid) or "OBDMID 0x%02X (unknown)" % mid


def tid_name(tid):
    return TID_NAMES.get(tid) or "TID 0x%02X (unknown)" % tid


def uas_name(uas):
    entry = UAS_IDS.get(uas)
    if not entry:
        return "UAS 0x%02X (unknown scaling)" % uas
    return "UAS 0x%02X (%s%s)" % (
        uas, entry["unit"] or "no unit",
        ", signed" if entry["signed"] else "")


def nrc_name(nrc):
    return NRC_NAMES.get(nrc) or "NRC 0x%02X (unknown)" % nrc


# --------------------------------------------------------------------------
# PID 0x1C - "OBD standards this vehicle conforms to" (SAE J1979 / ISO 15031-5)
# --------------------------------------------------------------------------

OBD_STANDARDS = {
    1: "OBD-II as defined by CARB",
    2: "OBD as defined by the EPA",
    3: "OBD and OBD-II",
    4: "OBD-I",
    5: "Not OBD compliant",
    6: "EOBD",
    7: "EOBD and OBD-II",
    8: "EOBD and OBD",
    9: "EOBD, OBD and OBD-II",
    10: "JOBD",
    11: "JOBD and OBD-II",
    12: "JOBD and EOBD",
    13: "JOBD, EOBD and OBD-II",
    14: "Engine Manufacturer Diagnostics (EMD)",
    15: "EMD Plus",
    16: "Heavy-Duty OBD (HD OBD-C)",
    17: "HD OBD",
    18: "WWH OBD",
    19: "HD EOBD-I",
    20: "HD EOBD-I N",
    21: "HD EOBD-II",
    22: "HD EOBD-II N",
    23: "Euro OBD stage VI",
    24: "Euro OBD stage VI (with NOx monitor)",
    25: "Euro OBD stage VI (with PM monitor)",
}


def obd_standard_name(code):
    """Human name for the PID 0x1C standards byte.

    Returns None when the byte is absent or out of the known range, so callers
    render "unknown" instead of inventing a standard.
    """
    if code is None:
        return None
    if isinstance(code, (bytes, bytearray)):
        code = int.from_bytes(bytes(code), "big")
    if not isinstance(code, int):
        return None
    return OBD_STANDARDS.get(code) or ("Standard byte 0x%02X (not in the J1979 table)" % code
                                       if code else None)


# --------------------------------------------------------------------------
# Service (mode) names, used in reports and error messages.
# --------------------------------------------------------------------------

MODE_NAMES = {
    0x01: "01 current data",
    0x02: "02 freeze frame",
    0x03: "03 stored DTCs",
    0x04: "04 clear DTCs",
    0x05: "05 O2 sensor monitor (legacy)",
    0x06: "06 on-board monitoring test results",
    0x07: "07 pending DTCs",
    0x08: "08 control of on-board systems",
    0x09: "09 vehicle information",
    0x0A: "0A permanent DTCs",
}


def mode_name(sid):
    return MODE_NAMES.get(sid) or "0x%02X (unknown service)" % sid


# --------------------------------------------------------------------------
# DTC categories (ISO 15031-6 / SAE J2012)
# --------------------------------------------------------------------------

DTC_CATEGORIES = {
    0: ("P", "Powertrain"),
    1: ("C", "Chassis"),
    2: ("B", "Body"),
    3: ("U", "Network"),
}


def dtc_category_label(first_char):
    for letter, label in DTC_CATEGORIES.values():
        if letter == first_char:
            return label
    return "Unknown"
