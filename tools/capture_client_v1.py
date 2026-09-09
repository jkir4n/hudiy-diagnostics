#!/usr/bin/env python3
"""Capture client that mimics charts.py exactly (HardenedClient + OBD subscription).
Run AFTER killing Hudiy and BEFORE restarting charts. Becomes first-served OBD client."""
import sys, threading, time, json
sys.path.insert(0, "/opt/hudiy-obd-charts")
import common.Api_pb2 as hudiy_api
from common.HardenedClient import HardenedClient

RESP_EVENTS, RESP_DATA = {}, {}
class H:
    def on_query_obd_device_response(self, client, message):
        ev = RESP_EVENTS.get(message.request_code)
        if ev is not None:
            RESP_DATA[message.request_code] = list(message.data); ev.set()
    def on_hello_response(self, client, message):
        subs = hudiy_api.SetStatusSubscriptions()
        subs.subscriptions.append(hudiy_api.SetStatusSubscriptions.Subscription.OBD)
        try:
            client.send(hudiy_api.MESSAGE_SET_STATUS_SUBSCRIPTIONS, 0, subs.SerializeToString())
        except Exception as e:
            print("sub fail:", e, flush=True)

client = HardenedClient("Chart")
client.connect("127.0.0.1", 44405)
try: client._socket.settimeout(30.0)
except Exception: pass
stop = threading.Event()
def reader():
    while not stop.is_set():
        try:
            if not client.wait_for_message(): break
        except Exception: break
t = threading.Thread(target=reader, daemon=True); t.start()
time.sleep(1.5)

def send_query(cmd, code, timeout=20.0):
    ev = threading.Event(); RESP_EVENTS[code] = ev; RESP_DATA[code] = None
    req = hudiy_api.QueryObdDeviceRequest(); req.commands[:] = [cmd]; req.request_code = code
    try:
        client.send(hudiy_api.MESSAGE_QUERY_OBD_DEVICE_REQUEST, 0, req.SerializeToString())
    except Exception as e:
        return False, {"error": str(e)}
    got = ev.wait(timeout=timeout)
    return got, RESP_DATA[code]

out = {}
# Wait for ELM device (ObdManager retry loop after Hudiy start): up to 20 min
print("capture client online; waiting for ELM device...", flush=True)
first_ok = None
for i in range(40):
    got, data = send_query("010C", 9000)
    if got:
        first_ok = data
        print(f"ELM LIVE at attempt {i+1}: {str(data)[:60]}", flush=True)
        out["010C"] = {"desc": "RPM", "answered": True, "raw": data}
        break
    time.sleep(4)

if first_ok is not None:
    QUERIES = [
        ("0A",   "permanent DTCs"),
        ("0104", "engine load"),
        ("0133", "baro pressure"),
        ("0685", "boost monitor"),
        ("0904", "CALID (guarded)"),
    ]
    for i, (cmd, desc) in enumerate(QUERIES):
        got, data = send_query(cmd, 9100 + i)
        out[cmd] = {"desc": desc, "answered": got, "raw": data}
        print(f"{cmd:5} -> {'OK ' if got else 'TIMEOUT'} {str(data)[:70]}", flush=True)
        if not got:
            print("ABORT after timeout", flush=True)
            break
        time.sleep(1.5)

stop.set()
try: client.disconnect()
except Exception: pass
json.dump(out, open("/tmp/diag_capture_final.json", "w"), indent=1)
print("WROTE /tmp/diag_capture_final.json", flush=True)
