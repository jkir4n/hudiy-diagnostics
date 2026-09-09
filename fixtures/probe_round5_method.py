#!/usr/bin/env python3
"""Round-5 targeted probe — missing fixtures. STRICT: abort on first timeout. Capped loops throughout."""
import sys, threading, time, json
sys.path.insert(0, "/opt/hudiy-obd-charts")
import common.Api_pb2 as hudiy_api
from common.Client import Client

RESP_EVENTS, RESP_DATA = {}, {}
class H:
    def on_query_obd_device_response(self, client, message):
        ev = RESP_EVENTS.get(message.request_code)
        if ev is not None:
            RESP_DATA[message.request_code] = list(message.data); ev.set()
    def on_hello_response(self, client, message):
        subs = hudiy_api.SetStatusSubscriptions()
        subs.subscriptions.append(hudiy_api.SetStatusSubscriptions.Subscription.OBD)
        client.send(hudiy_api.MESSAGE_SET_STATUS_SUBSCRIPTIONS, 0, subs.SerializeToString())

client = Client("diag-probe5")
client.set_event_handler(H())
client.connect("127.0.0.1", 44405)
try: client._socket.settimeout(15.0)
except Exception: pass
stop = threading.Event()
def reader():
    while not stop.is_set():
        try:
            if not client.wait_for_message(): break
        except Exception: break
t = threading.Thread(target=reader, daemon=True); t.start()
time.sleep(1.2)

QUERIES = [
    ("010C", "sanity RPM"),
    ("0A",   "permanent DTCs (clean answer)"),
    ("0104", "engine load (supported)"),
    ("0133", "barometric pressure (supported)"),
    ("0685", "boost monitor re-capture (clean 2-group)"),
    ("0904", "CALID (GUARDED - wedge suspect)"),
    ("0906", "CVN (only if 0904 clean)"),
]
out, aborted = {}, None
for i, (cmd, desc) in enumerate(QUERIES):
    code = 7400 + i
    ev = threading.Event(); RESP_EVENTS[code] = ev; RESP_DATA[code] = None
    req = hudiy_api.QueryObdDeviceRequest(); req.commands[:] = [cmd]; req.request_code = code
    try:
        client.send(hudiy_api.MESSAGE_QUERY_OBD_DEVICE_REQUEST, 0, req.SerializeToString())
    except Exception as e:
        out[cmd] = {"desc": desc, "error": str(e)}; aborted = cmd; break
    got = ev.wait(timeout=12.0)
    out[cmd] = {"desc": desc, "answered": got, "raw": RESP_DATA[code]}
    print(f"{cmd:5} -> {'OK ' if got else 'TIMEOUT'} {str(RESP_DATA[code])[:80]}", flush=True)
    if not got:
        aborted = cmd
        print(f"ABORT after timeout on {cmd}", flush=True)
        break
    time.sleep(1.2)

stop.set()
try: client.disconnect()
except Exception: pass
out["_aborted_after"] = aborted
json.dump(out, open("/tmp/diag_probe5.json", "w"), indent=1)
print("WROTE /tmp/diag_probe5.json aborted_after=", aborted, flush=True)
