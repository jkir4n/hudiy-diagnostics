import sys
src = open("/tmp/charts_capture.py").read()

NL = chr(10)
old = "    def on_query_obd_device_response(self, client, message):" + NL + "        with pending_lock:"
new_block = (
    "    def on_query_obd_device_response(self, client, message):" + NL +
    "        try:" + NL +
    "            if message.request_code >= 910000 and message.result:" + NL +
    '                with open("/tmp/capture_inject.jsonl", "a") as f:' + NL +
    '                    f.write(json.dumps({"req": message.request_code, "data": list(message.data), "ts": time.time()}) + chr(10))' + NL +
    "        except Exception:" + NL +
    "            pass" + NL +
    "        with pending_lock:"
)
assert old in src, "A"
src = src.replace(old, new_block, 1)

cap = (
    NL +
    'CAPTURE_PIDS = ["0A", "0104", "0133", "0685", "0904", "0906"]' + NL + NL +
    "def _capture_thread():" + NL +
    "    deadline = time.monotonic() + 600" + NL +
    "    cycle = 0" + NL +
    "    while time.monotonic() < deadline and cycle < 8:" + NL +
    "        cycle += 1" + NL +
    "        base = 910000 + cycle * 10" + NL +
    "        for i, pid in enumerate(CAPTURE_PIDS):" + NL +
    "            req_id = base + i" + NL +
    "            try:" + NL +
    "                ok = send_obd_query(pid, req_id)" + NL +
    "            except Exception:" + NL +
    "                ok = False" + NL +
    '            with open("/tmp/capture_inject.log", "a") as f:' + NL +
    '                f.write(str(time.time()) + " send " + pid + " req=" + str(req_id) + " ok=" + str(ok))' + NL +
    '                f.write(chr(10))' + NL +
    "            _shutdown_event.wait(3.0)" + NL +
    "        _shutdown_event.wait(10.0)" + NL +
    '    with open("/tmp/capture_inject.log", "a") as f:' + NL +
    '        f.write(str(time.time()) + " capture thread done cycles=" + str(cycle))' + NL +
    '        f.write(chr(10))' + NL + NL
)
anchor = "def run_api():"
assert anchor in src, "B"
src = src.replace(anchor, cap + anchor, 1)

old_start = "    _poller_thread = threading.Thread(target=_background_obd_poller, daemon=True)" + NL + "    _poller_thread.start()"
new_start = old_start + NL + "    threading.Thread(target=_capture_thread, daemon=True).start()"
assert old_start in src, "C"
src = src.replace(old_start, new_start, 1)

if "import json" not in src:
    src = src.replace("import time", "import time" + NL + "import json", 1)

open("/tmp/charts_capture.py", "w").write(src)
print("PATCH2-OK")
