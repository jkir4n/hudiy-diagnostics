/* Hudiy Diagnostics - overlay page logic (V1_SPEC screens S0-S8).
 *
 * Design notes
 * ------------
 * Input parity (V1_SPEC rule 6): every action on every screen is reachable by
 * touch, mouse (click + wheel), or whatever controller the user has - Hudiy
 * delivers knobs/keyboards/remotes to its web views through the bridge
 * documented in docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md. That is the primary
 * path, and it is Hudiy's own contract, not an app-specific scheme:
 * window.hudiy carries inputFocus/activated plus onMoveToNextControl /
 * onMoveToPreviousControl (return true when the page consumed the key, false
 * to hand it back to Hudiy), onTriggered, onGoBack, onGoLeft/onGoRight.
 * A DOM keydown + wheel fallback drives exactly the same state machine for
 * browser testing and for installs where the bridge is absent.
 * localStorage ("diag.bridge") / "?bridge=" / the settings screen pick the path
 * (auto-detect by default: bridge once Hudiy attaches, DOM until then).
 *
 * The page never talks to the OBD adapter. It reads the backend HTTP lane only
 * (same origin, so no CORS dance): /health, /scan, /report, /capability,
 * /dtc, /vin. Everything the UI shows comes from those responses - no vehicle
 * knowledge is baked in here.
 */

(function () {
  'use strict';

  var HEALTH_MS = 5000;      // slow poll: link state + replay badge
  var SCAN_LINK_MS = 1200;   // faster only while a scan is in flight
  var SECTIONS = ['discovery', 'dtc', 'pending', 'readiness', 'mode06', 'identity', 'live', 'allpids'];
  var DEEP = ['discovery', 'allpids'];
  var QUICK = ['dtc', 'pending', 'readiness'];
  var TOAST_MS = 5200;

  /* ------------------------------------------------------------------ copy */

  // Driver-facing copy, British English, wording kept stable (see
  // docs/DIESEL_READINESS_FINDINGS.md section 4 - paste-ready blocks).
  var COPY = {
    afterClear:
      'Your car\'s self-checks were reset when the fault codes were cleared, so each emissions ' +
      'system must prove itself healthy again before the car can report it as Ready. This is ' +
      'normal and does not mean anything is broken - the checks (called readiness monitors) ' +
      'simply have not run yet. It usually takes a few days of mixed town and motorway driving, ' +
      'including starting the car from fully cold, before they all complete. Avoid clearing the ' +
      'codes again in the meantime, as that restarts the whole waiting period from zero.',
    dieselEgr:
      'The exhaust-gas-recirculation (EGR) check and the turbo-boost check only run when the ' +
      'engine is fully warmed up and sees particular kinds of driving, such as steady cruising ' +
      'followed by easing off the accelerator without braking. Short trips around town almost ' +
      'never include those moments, so these two monitors are often the last to turn Ready. ' +
      'Give the car a longer run with some steady motorway cruising and gentle slow-downs, and ' +
      'they will usually complete on their own. If they still refuse after several such drives, ' +
      'the system may be finding a real fault and it is worth having it diagnosed rather than ' +
      'driving further.',
    driveCycle:
      'Start with the car parked overnight so the engine is genuinely cold, keep the fuel tank ' +
      'between a quarter and three quarters full, and check no warning lights or fault codes ' +
      'are present. Then drive a mix: a few minutes of gentle town driving, about ten minutes ' +
      'of steady motorway cruising using cruise control if you have it, one long ease off the ' +
      'accelerator without braking, and a couple of minutes idling at the end. Repeat with ' +
      'another cold start the next day rather than doing one giant trip, because most checks ' +
      'need to see two or three cold starts to sign off. If a single monitor is still not Ready ' +
      'after three such drives, stop repeating the cycle and get that system checked - the test ' +
      'is probably running and failing, not waiting for better driving.',
    freezeFrame:
      'This ECU does not support freeze-frame snapshots (Mode 02), so no engine data was stored ' +
      'alongside the code. That is a capability of the car, not a fault in this app.',
    milSteady:
      'The warning light is on. The ECU has an emissions fault stored - get it diagnosed soon ' +
      'and drive gently until then.',
    misfire:
      'A misfire can destroy the catalyst if it keeps running. Get it looked at soon and drive ' +
      'gently; if the light ever flashes, stop as soon as it is safe.',
    pending:
      'A test failed once. The warning light stays off and nothing is stored until the fault ' +
      'repeats on the next trip, so this is being watched rather than a failure.',
    permanent:
      'A permanent code cannot be erased by any scan tool or battery disconnect. It clears only ' +
      'when the ECU itself verifies the repair over later drives.',
    noReport:
      'No report has been produced on this backend yet. Run a scan, or fetch a report after one ' +
      'has completed.',
    clearCodes:
      'Fault codes can be cleared from the Fault codes screen once a scan has ' +
      'found any: the entry button appears there while the ECU link is online. ' +
      'Clearing is a two-step confirm, and every clear resets all readiness ' +
      'monitors to Not ready.',
    clearLead:
      'Clearing sends a Mode 04 reset to the ECU. Read this first - ' +
      'the reset cannot be undone, and the list below is the full cost.',
    clearEffects: [
      'Stored fault codes are erased, along with freeze-frame snapshots and ' +
      'the last monitor-test results held alongside them.',
      'Every readiness monitor resets to Not ready. The car will not pass an ' +
      'emissions test until a full drive cycle re-completes them - on a diesel ' +
      'that is typically 60 to 90 minutes of specific driving, or more.',
      'The car may run slightly roughly for a while afterwards, while the ECU ' +
      're-learns its fuel trims.',
      'If the underlying fault is not repaired, the codes will come straight back.'
    ],
    clearFixFirst:
      'I understand the codes will return if the fault is not repaired, and ' +
      'that this resets all emissions self-tests',
    clearClearNow: 'Clear now',
    clearBack: 'Back to codes',
    clearWorking: 'Sending the reset to the ECU',
    clearDoneHead: 'Fault codes cleared',
    clearFollowTitle: 'What happens next',
    clearGuideShow: 'Show drive-cycle guidance',
    clearGuideHide: 'Hide drive-cycle guidance',
    clearTimeout:
      'The clear request timed out - the ECU did not confirm in time. ' +
      'The codes may or may not have been erased: run a scan and check ' +
      'before trying again.',
    clearBusy:
      'A clear is already running on the backend. Wait for it to finish ' +
      'before trying again.',
    clearCancelled:
      'Clear cancelled before the ECU answered. Nothing was confirmed, so ' +
      'run a scan to see what the ECU still holds.',
    clearNetFail:
      'Clear failed: the backend did not answer. Nothing was confirmed, so ' +
      'run a scan to see what the ECU still holds before trying again.',
    clearReread:
      'Re-reading the readiness wall to show the reset state.',
    clearRereadFail:
      'The follow-up re-read did not answer - the reset result above still ' +
      'stands. Open the readiness wall to check the monitors directly.',
    clearOffline:
      'The ECU link is not online, so clearing is unavailable. ' +
      'Wait for the link to reconnect first.'
  };

  var HINTS = {
    misfire: 'Any two cold starts with a few minutes of normal driving.',
    fuel_system: 'A cold start, then steady driving at a light throttle.',
    components: 'Any two cold starts with a few minutes of normal driving.',
    egr_vvt: 'Warmed-up steady cruise, then ease off the accelerator without braking.',
    boost_pressure: 'Warmed-up steady cruise, then ease off the accelerator without braking.',
    pm_filter: 'A long, hot run at motorway speed; short trips will not finish it.',
    nox_scr: 'A long, hot run at motorway speed; short trips will not finish it.',
    exhaust_gas_sensor: 'A warmed-up cruise with a couple of gentle coasts.',
    o2_sensor: 'A cold start followed by a steady cruise and a gentle coast.',
    o2_sensor_heater: 'A cold start followed by a few minutes of normal driving.',
    catalyst: 'A cold start followed by a steady cruise and a gentle coast.',
    heated_catalyst: 'A cold start followed by a few minutes of normal driving.',
    evaporative: 'A cold start, then a steady run with the tank between a quarter and three quarters.',
    secondary_air: 'A cold start followed by a few minutes of normal driving.',
    gpf: 'A long, warm run at a steady speed.',
    _: 'A cold start plus a steady cruise and a gentle coast.'
  };

  var MONITOR_WORD = {
    complete: { sev: 'ok', word: 'Ready', glyph: '\u2713' },
    incomplete: { sev: 'warn', word: 'Not ready', glyph: '!' },
    na: { sev: 'quiet', word: 'Not on this car', glyph: '\u2013' },
    reserved: { sev: 'quiet', word: 'Reserved', glyph: '\u2013' }
  };

  var LINK_WORD = {
    online: 'ECU connected',
    scanning: 'Reading the ECU',
    'stale-handle': 'ECU reconnecting',
    reconnecting: 'ECU reconnecting',
    offline: 'ECU not answering',
    unavailable: 'Lane unavailable',
    unknown: 'Link state unknown'
  };

  /* ------------------------------------------------------------------ dom */

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = String(text); }
    return n;
  }

  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  function add(parent) {
    for (var i = 1; i < arguments.length; i++) {
      if (arguments[i]) { parent.appendChild(arguments[i]); }
    }
    return parent;
  }

  function chip(sev, glyph, word) {
    var c = el('span', 'chip chip-sev-' + sev);
    if (glyph) { add(c, el('span', null, glyph)); }
    add(c, el('span', null, word));
    return c;
  }

  function num(value, digits) {
    if (value === null || value === undefined || value === '') { return '\u2013'; }
    if (typeof value !== 'number') { return String(value); }
    return (digits === undefined ? String(value) : value.toFixed(digits));
  }

  /* ---------------------------------------------------------------- state */

  var S = {
    screen: 'S0',
    health: null,
    healthErr: null,
    scan: null,          // full /scan payload once a scan has finished
    scanAt: null,
    degraded: null,      // {status, reason} when /scan answered offline/unavailable
    dtcTab: 'stored',
    dtcIndex: 0,
    detail: null,        // {kind, entry, lookup, state, error}
    vin: null,
    vinState: 'idle',
    vinOnline: null,
    reportFmt: 'text',
    reportBody: null,
    reportState: 'idle',
    scope: 'full',
    bridge: 'auto',
    attached: false,
    focus: 0,
    kb: false,
    busy: false,
    guidance: false,
    raw: false,
    expanded: {},    // Mode 06 raw expanders, key "obdmid:tid" -> true
    deep: null,      // deep-scan result {rows, at, duration_s} - never clobbers S.scan
    cap: null,       // capability JSON once /capability has answered
    capText: null,   // paste-ready sheet text for the export actions
    capState: 'idle',
    clear: null,     // Mode 04 flow state once the S11 screen has opened
    clearAbort: null, // in-flight POST /clear controller (single-flight)
    clearBusy: false, // true while a clear request is on the wire
    scanKind: null,  // 'full' | 'quick' | 'deep' while S.busy
    scanSections: null, // legend filter for the in-flight scan (S1)
    started: 0,
    scanAbort: null,
    linkTimer: null,
    tickTimer: null
  };

  var SCREENS = {
    S0: { title: 'Diagnostics', subtitle: 'Vehicle scan' },
    S1: { title: 'Scanning', subtitle: 'Reading the ECU' },
    S2: { title: 'Health summary', subtitle: '' },
    S3: { title: 'Fault codes', subtitle: '' },
    S4: { title: 'Fault code', subtitle: '' },
    S5: { title: 'Readiness', subtitle: 'Monitor wall' },
    S6: { title: 'Monitor tests', subtitle: 'Mode 06' },
    S7: { title: 'Vehicle', subtitle: 'Identity' },
    S8: { title: 'Report', subtitle: 'Settings' },
    S9: { title: 'Deep scan', subtitle: 'Every advertised PID' },
    S10: { title: 'Compatibility', subtitle: 'This car, this app' },
    S11: { title: 'Clear fault codes', subtitle: 'Mode 04 reset' }
  };

  var PARENT = { S1: 'S0', S2: 'S0', S3: 'S2', S4: 'S3', S5: 'S2', S6: 'S2', S7: 'S2', S8: 'S0', S9: 'S2', S10: 'S8', S11: 'S3' };

  function screenEl(id) { return $(id || S.screen); }

  /* ------------------------------------------------------------- storage */

  function store(key, value) {
    try {
      if (value === undefined) { return window.localStorage.getItem('diag.' + key); }
      window.localStorage.setItem('diag.' + key, value);
    } catch (err) { /* private mode / no storage: settings simply do not persist */ }
    return null;
  }

  function param(name) {
    var m = new RegExp('[?&]' + name + '=([^&]+)').exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function boot() {
    var q = param('bridge');
    if (q === 'bridge' || q === 'dom' || q === 'auto') { S.bridge = q; }
    else {
      var saved = store('bridge');
      S.bridge = (saved === 'bridge' || saved === 'dom' || saved === 'auto') ? saved : 'auto';
    }
    var scope = store('scope');
    S.scope = (scope === 'quick' || scope === 'full') ? scope : 'full';
    document.body.setAttribute('data-bridge', S.bridge);
  }

  function effectiveBridge() {
    if (S.bridge === 'bridge' || S.bridge === 'dom') { return S.bridge; }
    return S.attached ? 'bridge' : 'dom';
  }

  /* --------------------------------------------------------------- render */

  function go(id) {
    if (!SCREENS[id]) { return false; }
    S.screen = id;
    S.focus = 0;
    document.body.setAttribute('data-screen', id);
    var sections = document.querySelectorAll('.screen');
    for (var i = 0; i < sections.length; i++) {
      sections[i].classList.toggle('active', sections[i].id === id);
    }
    var meta = SCREENS[id];
    $('title').textContent = meta.title;
    $('subtitle').textContent = meta.subtitle || '';
    $('back').hidden = (id === 'S0');
    render();
    return true;
  }

  function render() {
    renderHeader();
    if (S.screen === 'S0') { renderHome(); }
    if (S.screen === 'S1') { renderScan(); }
    if (S.screen === 'S2') { renderSummary(); }
    if (S.screen === 'S3') { renderCodes(); }
    if (S.screen === 'S4') { renderDetail(); }
    if (S.screen === 'S5') { renderReadiness(); }
    if (S.screen === 'S6') { renderTests(); }
    if (S.screen === 'S7') { renderIdentity(); }
    if (S.screen === 'S8') { renderReport(); }
    if (S.screen === 'S9') { renderDeep(); }
    if (S.screen === 'S10') { renderCompat(); }
    if (S.screen === 'S11') { renderClear(); }
    renderActions();
    paintFocus();
  }

  function renderHeader() {
    var obd = S.health && S.health.obd ? S.health.obd : null;
    var state = obd && obd.state ? obd.state : 'unknown';
    if (S.busy && state === 'unknown') { state = 'scanning'; }
    var pill = $('link');
    pill.setAttribute('data-state', state);
    var word = LINK_WORD[state] || ('Link: ' + state);
    if (obd && obd.reason) { word += ' \u2014 ' + obd.reason; }
    pill.textContent = word;
    pill.title = word;

    var host = obd && obd.host ? obd.host : null;
    var replay = (host && host.source === 'replay') || (obd && obd.fixture);
    $('modeTag').hidden = !replay;
    if (replay) { $('modeTag').textContent = 'Replay data'; }
    renderStateBar();
  }

  /* Hudiy-chip bottom state row (HUDIY_UI_LANGUAGE target F): two live pill
   * chips (ECU link state, last scan outcome) plus a static scope chip.
   * Same severity mapping as everywhere else: dot + colour, never colour
   * alone - the chip also carries a short word. */
  var STATE_SEV = {
    online: 'ok', scanning: 'info', 'stale-handle': 'warn', reconnecting: 'warn',
    offline: 'bad', unavailable: 'bad', unknown: 'quiet'
  };

  function setChip(id, sev, word, title) {
    var chipEl = $(id);
    chipEl.setAttribute('data-sev', sev || 'quiet');
    chipEl.title = title || word;
    clear(chipEl);
    var dot = document.createElement('i');
    dot.setAttribute('aria-hidden', 'true');
    chipEl.appendChild(dot);
    chipEl.appendChild(document.createTextNode(word));
  }

  function renderStateBar() {
    var obd = S.health && S.health.obd ? S.health.obd : null;
    var state = obd && obd.state ? obd.state : 'unknown';
    if (S.busy && state === 'unknown') { state = 'scanning'; }
    setChip('chipLink', STATE_SEV[state], LINK_WORD[state] || ('Link: ' + state),
      'ECU link ' + state);
    var scanSev = 'quiet';
    var scanWord = 'No scan yet';
    if (S.busy) { scanSev = 'info'; scanWord = 'Scanning\u2026'; }
    else if (S.degraded) { scanSev = 'bad'; scanWord = 'Scan failed'; }
    else if (S.scan) {
      var ready = S.scan.report && S.scan.report.readiness ? S.scan.report.readiness : null;
      var sev = ready ? sevFromVerdict(ready.verdict) : 'info';
      scanSev = sev === 'quiet' ? 'info' : sev;
      scanWord = 'Scan ' + (ready ? verdictWord(ready.verdict) : 'read');
    }
    setChip('chipScan', scanSev, scanWord,
      S.scan ? ('Last scan: ' + (S.scan.summary || 'complete')) : 'No scan has run yet');
    var scope = S.scope === 'quick' ? 'Quick scope' : 'Full scope';
    setChip('chipInfo', 'quiet', scope, 'Scan scope setting lives on the Report screen');
  }

  /* ------------------------------------------------------------- S0 home */

  function renderHome() {
    var obd = S.health && S.health.obd ? S.health.obd : null;
    var state = obd && obd.state ? obd.state : 'unknown';
    var hero = $('s0Hero');
    hero.setAttribute('data-state', state);
    $('s0State').textContent = LINK_WORD[state] || 'Link state unknown';

    var note;
    if (S.degraded) {
      note = 'Last scan could not run: ' + (S.degraded.reason || S.degraded.status) + '.';
    } else if (S.scan) {
      note = 'Last scan: ' + (S.scan.summary || 'complete') + ' (' + num(S.scan.duration_s, 1) + ' s).';
    } else if (obd && obd.last_ok_age_s !== null && obd.last_ok_age_s !== undefined) {
      note = 'Last ECU answer ' + num(obd.last_ok_age_s, 1) + ' s ago. No scan has run on this screen yet.';
    } else {
      note = 'No scan has run on this screen yet.';
    }
    $('s0Note').textContent = note;
  }

  /* ------------------------------------------------------------- S1 scan */

  function renderScan() {
    syncScanMotion();   // motion pass: shimmer + spinner states ride S.busy
    var steps = $('scanSteps');
    if (S.scan) { return; }
    if (!steps.children.length) {
      for (var i = 0; i < SECTIONS.length; i++) {
        var li = el('li', null, SECTIONS[i]);
        li.setAttribute('data-section', SECTIONS[i]);
        li.setAttribute('data-done', '0');
        steps.appendChild(li);
      }
    }
    $('scanTimer').textContent = num(S.elapsed, 1) + 's';
    var note = S.scanKind === 'deep'
      ? 'Deep read: every PID this car advertises, read one by one and decoded where the table knows it.'
      : (S.scope === 'quick'
        ? 'Quick scan: fault codes, pending codes and the readiness wall only.'
        : 'A full scan reads the supported-PID map, stored / pending / permanent codes, the ' +
          'readiness wall, Mode 06 monitor tests, vehicle identity and every advertised PID ' +
          '- usually under a minute on a live link.');
    if (S.degraded && S.scanKind !== 'deep') { note = 'Last attempt: ' + (S.degraded.reason || S.degraded.status) + '.'; }
    $('scanNote').textContent = note;
    var sec = S.scanSections;
    for (var j = 0; j < steps.children.length; j++) {
      var name = steps.children[j].getAttribute('data-section');
      var wanted = !sec || sec.indexOf(name) !== -1;
      var done = !!(S.scan && wanted);
      steps.children[j].setAttribute('data-done', done ? '1' : '0');
      steps.children[j].style.display = wanted ? '' : 'none';
    }
  }

  /* ---------------------------------------------------------- S2 summary */

  function sevFromVerdict(verdict) {
    if (verdict === 'ready') { return 'ok'; }
    if (verdict === 'not_ready') { return 'warn'; }
    if (verdict === 'mil_on') { return 'bad'; }
    if (verdict === 'codes_present') { return 'warn'; }
    return 'info';
  }

  function renderSummary() {
    var card = $('verdict');
    clear(card);
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var ready = report && report.readiness ? report.readiness : null;
    var codes = report && report.codes ? report.codes : null;
    var sev = 'info';

    if (S.degraded) {
      card.setAttribute('data-sev', 'bad');
      add(card, el('p', 'verdict-headline', 'No scan data'));
      add(card, el('p', 'verdict-sub', S.degraded.reason || 'The diagnostics lane did not answer.'));
      add(card, el('p', 'verdict-rule', 'State: ' + S.degraded.status + '. Nothing is cached, so no verdict is shown.'));
      $('tilesHub').style.display = 'none';
      $('scanStamp').textContent = '';
      return;
    }

    $('tilesHub').style.display = '';

    if (!ready) {
      card.setAttribute('data-sev', 'info');
      add(card, el('p', 'verdict-headline', 'Scan finished with gaps'));
      add(card, el('p', 'verdict-sub',
        'The readiness wall is missing from this scan, so no verdict can be given.'));
      add(card, el('p', 'verdict-rule', 'Sections returned: ' +
        ((S.scan.sections || ['(full)']).join(', '))));
    } else {
      sev = sevFromVerdict(ready.verdict);
      card.setAttribute('data-sev', sev);
      var head = add(card, el('div', 'verdict-head'));
      add(head, el('p', 'verdict-headline', ready.headline || 'Readiness'));
      add(head, chip(sev, sev === 'ok' ? '\u2713' : (sev === 'bad' ? '!' : '!'), verdictWord(ready.verdict)));
      var sub = readinessSentence(ready, codes);
      add(card, el('p', 'verdict-sub', sub));
      add(card, el('p', 'verdict-rule', (ready.rule && ready.rule.label ? ready.rule.label : 'Rule')
        + ' \u2014 ' + (ready.counted_count || 0) + ' monitor(s) still open within this rule'));

      var counts = el('div', 'counts');
      add(counts, countBox(num(codes ? codes.dtc_count : 0, 0), 'Fault codes',
        codes && codes.dtc_count ? 'bad' : 'ok'));
      add(counts, countBox(codes && codes.mil ? 'On' : 'Off', 'Warning light',
        codes && codes.mil ? 'bad' : 'ok'));
      var open = (ready.incomplete || []).length;
      add(counts, countBox(num(open, 0), 'Monitors open', open ? 'warn' : 'ok'));
      add(counts, countBox(num((report.monitor_tests || []).length, 0), 'Tests read', 'info'));
      add(card, counts);
    }

    renderTiles();
    $('scanStamp').textContent = 'Scan ' + (S.scanAt ? S.scanAt.toLocaleTimeString() : '\u2013') +
      ' \u00b7 ' + num(S.scan.duration_s, 1) + ' s \u00b7 lane ' +
      ((S.scan.obd && S.scan.obd.host_name) ? S.scan.obd.host_name : 'unknown');
    // motion pass: fresh verdict cross-fades in once per scan, not per render
    revealOnce(card, 'scan:' + (S.scanAt ? S.scanAt.getTime() : 'none'));
  }

  function countBox(value, label, tone) {
    var box = el('div', 'count');
    box.setAttribute('data-tone', tone || '');
    add(box, el('b', null, value), el('span', null, label));
    return box;
  }

  function verdictWord(verdict) {
    if (verdict === 'ready') { return 'Ready'; }
    if (verdict === 'not_ready') { return 'Not ready'; }
    if (verdict === 'mil_on') { return 'Light on'; }
    if (verdict === 'codes_present') { return 'Codes stored'; }
    return 'Unclear';
  }

  function readinessSentence(ready, codes) {
    var parts = [];
    if (ready.verdict === 'ready') {
      parts.push('Every monitor this car supports has finished its self-check.');
    } else if (ready.verdict === 'not_ready') {
      parts.push((ready.incomplete || []).length + ' monitor(s) have not finished their self-check yet.');
    } else if (ready.verdict === 'mil_on') {
      parts.push(COPY.milSteady);
    } else if (ready.verdict === 'codes_present') {
      parts.push('Fault codes are stored, so the self-check wall has to be read alongside them.');
    } else {
      parts.push('The ECU did not report enough for a readiness verdict.');
    }
    if (codes && codes.mil && ready.verdict !== 'mil_on') { parts.push(COPY.milSteady); }
    if (ready.inputs_missing && ready.inputs_missing.length) {
      parts.push('Missing input(s): ' + ready.inputs_missing.join(', ') + '.');
    }
    parts.push('Readiness rules differ by country and model year, so this is not an inspection result.');
    return parts.join(' ');
  }

  function renderTiles() {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var wrap = S.screen === 'S0' ? null : $('tilesHub');
    if (S.screen === 'S0') {
      // S0 keeps a single start card; the tiles live on S2 only.
      return;
    }
    if (!wrap) { return; }
    clear(wrap);
    var ready = S.scan && !S.degraded && report.readiness ? report.readiness : null;
    var codes = S.scan && !S.degraded && report.codes ? report.codes : null;
    var tests = S.scan && !S.degraded ? (report.monitor_tests || []) : [];
    var vehicle = report && report.vehicle ? report.vehicle : null;

    var faultValue = S.degraded ? '\u2013' : (codes ? num(codes.dtc_count, 0) : '\u2013');
    var faultSub = !S.degraded && codes
      ? ((codes.stored || []).length + ' stored \u00b7 ' + (codes.mil ? 'light on' : 'light off'))
      : 'No data';
    var readyValue = S.degraded ? '\u2013' : (ready ? verdictWord(ready.verdict) : '\u2013');
    var readySub = !S.degraded && ready ? ((ready.incomplete || []).length + ' monitor(s) open') : 'No data';
    var outside = 0;
    tests.forEach(function (rec) {
      (rec.tests || []).forEach(function (t) { if (t.within_limits === false) { outside++; } });
    });
    var advValue = S.degraded ? '\u2013' : (tests.length + ' MID' + (tests.length === 1 ? '' : 's'));
    var advSub = S.degraded ? 'No data' : (outside ? (outside + ' test(s) outside limits') : 'all within limits');
    var vin = vehicle && vehicle.vin ? vehicle.vin : null;

    add(wrap, tile('Fault codes', faultValue, faultSub, function () { go('S3'); }, true, false));
    add(wrap, tile('Readiness', readyValue, readySub, function () { go('S5'); }, true, true));
    add(wrap, tile('Monitor tests', advValue, advSub, function () { go('S6'); }, true, false));
    add(wrap, tile('Vehicle', vin ? (vin.slice(-7)) : '\u2013',
      vin ? 'VIN on file' : 'No VIN read', function () { go('S7'); }, true, true));
  }

  function tile(label, value, sub, onTap, enabled, small) {
    var b = el('button', 'tile ctl');
    b.type = 'button';
    b.disabled = !enabled;
    add(b, el('span', 'tile-label', label));
    add(b, el('span', 'tile-value' + (small ? ' small' : ''), value));
    add(b, el('span', 'tile-sub', sub));
    b.addEventListener('click', onTap);
    return b;
  }

  /* -------------------------------------------------------- S3 code list */

  function codeList(kind) {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var codes = report && report.codes ? report.codes : null;
    if (!codes) { return []; }
    return codes[kind] || [];
  }

  function severityOf(entry, kind) {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var codes = report && report.codes ? report.codes : null;
    var mil = !!(codes && codes.mil);
    var code = (entry && entry.code) ? String(entry.code) : '';
    if (kind === 'permanent') {
      return { sev: 'warn', word: 'Permanent', glyph: '!', note: COPY.permanent };
    }
    if (/^P03/i.test(code) && kind === 'stored') {
      return { sev: 'bad', word: 'Stop soon', glyph: '!', note: COPY.misfire };
    }
    if (kind === 'pending') {
      return { sev: 'info', word: 'Being watched', glyph: '\u2013', note: COPY.pending };
    }
    if (mil) {
      return { sev: 'bad', word: 'Light on', glyph: '!', note: COPY.milSteady };
    }
    return {
      sev: 'warn', word: 'Stored', glyph: '!',
      note: 'The ECU stored this as a confirmed fault. The warning light is off right now, which ' +
            'means it has cleared after clean trips - the code itself lingers in memory.'
    };
  }

  function lookupOf(entry) {
    if (!entry) { return null; }
    if (entry.lookup && entry.lookup.available) { return entry.lookup; }
    return null;
  }

  function codeText(entry) {
    var lk = lookupOf(entry);
    if (lk && lk.generic && lk.generic.description) { return lk.generic.description; }
    if (lk && lk.manufacturer_specific && lk.manufacturer_specific.description) {
      return lk.manufacturer_specific.description;
    }
    if (entry && entry.known === false) { return 'Not in the offline code table'; }
    return 'No description available';
  }

  function renderCodes() {
    var tabs = $('dtcTabs');
    var list = $('dtcList');
    var empty = $('dtcEmpty');
    clear(tabs);
    clear(list);

    var counts = { stored: codeList('stored').length, pending: codeList('pending').length,
                   permanent: codeList('permanent').length };
    var kinds = ['stored', 'pending', 'permanent'];
    kinds.forEach(function (kind) {
      var b = el('button', 'tab ctl');
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', S.dtcTab === kind ? 'true' : 'false');
      b.textContent = kind.charAt(0).toUpperCase() + kind.slice(1) + ' ';
      add(b, el('span', 'n', counts[kind]));
      b.addEventListener('click', function () { S.dtcTab = kind; S.dtcIndex = 0; render(); });
      tabs.appendChild(b);
    });

    var entries = codeList(S.dtcTab);
    if (!entries.length) {
      empty.hidden = false;
      var report = S.scan && S.scan.report ? S.scan.report : null;
      var queries = report && report.codes ? report.codes.queries : null;
      var q = queries && queries[{ stored: '03', pending: '07', permanent: '0A' }[S.dtcTab]];
      if (q && q.supported === false) {
        empty.textContent = 'This car does not report ' + S.dtcTab + ' codes at all (Mode ' +
          { stored: '03', pending: '07', permanent: '0A' }[S.dtcTab] + ' answered ' + q.status + ').';
      } else {
        empty.textContent = 'No ' + S.dtcTab + ' codes. The ECU answered this query and had nothing to report.';
      }
      return;
    }
    empty.hidden = true;

    entries.forEach(function (entry, index) {
      var sev = severityOf(entry, S.dtcTab);
      var li = el('li');
      var row = el('button', 'row ctl');
      row.type = 'button';
      add(row, el('span', 'row-code', entry.code || '?'));
      var main = el('div', 'row-main');
      add(main, el('div', 'row-text', codeText(entry)));
      var bits = [];
      if (entry.category) { bits.push('category ' + entry.category); }
      if (entry.bytes) { bits.push('bytes ' + entry.bytes); }
      if (entry.known === false) { bits.push('outside the offline table'); }
      bits.push(S.dtcTab);
      add(main, el('div', 'row-sub', bits.join(' \u00b7 ')));
      add(row, main, chip(sev.sev, sev.glyph, sev.word));
      row.addEventListener('click', function () { openDetail(index); });
      add(li, row);
      list.appendChild(li);
    });
  }

  /* ------------------------------------------------------- S4 code detail */

  function openDetail(index) {
    var entries = codeList(S.dtcTab);
    if (!entries[index]) { return; }
    S.dtcIndex = index;
    var entry = entries[index];
    S.detail = { kind: S.dtcTab, entry: entry, lookup: lookupOf(entry), state: lookupOf(entry) ? 'done' : 'loading', error: null };
    go('S4');
    if (S.detail.state === 'loading') { fetchLookup(entry.code); }
  }

  function fetchLookup(code) {
    if (!code) { return; }
    var want = code;
    fetchJSON('/dtc?code=' + encodeURIComponent(code)).then(function (res) {
      if (!S.detail || S.detail.entry.code !== want) { return; }
      if (res.ok && res.data && res.data.lookup) {
        S.detail.lookup = res.data.lookup;
        S.detail.state = 'done';
      } else {
        S.detail.state = 'error';
        S.detail.error = res.error || 'Lookup failed';
      }
      if (S.screen === 'S4') { render(); }
    });
  }

  function renderDetail() {
    var box = $('dtcDetail');
    clear(box);
    var d = S.detail;
    if (!d) {
      add(box, el('p', 'empty', 'No code selected.'));
      return;
    }
    var entry = d.entry || {};
    var sev = severityOf(entry, d.kind);
    var head = el('div', 'detail-head');
    add(head, el('span', 'detail-code', entry.code || '?'));
    add(head, chip(sev.sev, sev.glyph, sev.word));
    add(head, el('span', 'row-sub', d.kind));
    add(box, head);

    var text = el('div', 'detail-block');
    add(text, el('h3', null, 'What it means'));
    if (d.state === 'loading') {
      add(text, el('p', null, 'Looking the code up\u2026'));
    } else if (d.state === 'error') {
      add(text, el('p', null, 'Lookup unavailable: ' + (d.error || 'the backend did not answer') + '.'));
    } else {
      var lk = d.lookup || {};
      var desc = (lk.generic && lk.generic.description) ||
                 (lk.manufacturer_specific && lk.manufacturer_specific.description);
      add(text, el('p', null, desc || 'This code is not in the offline table.'));
      if (lk.manufacturer_specific && lk.manufacturer_specific.description && lk.generic && lk.generic.description) {
        add(text, el('p', null, 'Manufacturer-specific: ' + lk.manufacturer_specific.description +
          (lk.manufacturer ? ' (' + lk.manufacturer + ')' : '')));
      }
      if (!desc && lk.reason) { add(text, el('p', null, 'Reason given: ' + lk.reason)); }
      if (lk.found === false) { add(text, el('p', null, 'The offline table has no entry for this code.')); }
    }
    add(box, text);

    var advice = el('div', 'detail-block');
    add(advice, el('h3', null, 'What to do'));
    add(advice, el('p', null, sev.note));
    add(box, advice);

    var facts = el('div', 'detail-block');
    add(facts, el('h3', null, 'Detail'));
    var dl = el('dl');
    add(dl, kv('Category', entry.category || '\u2013'));
    add(dl, kv('Raw bytes', entry.bytes || '\u2013'));
    add(dl, kv('Code table', entry.known === false ? 'no offline entry' : 'offline entry found'));
    add(dl, kv('Freeze frame', freezeFrameLine()));
    var q = queryLine(d.kind);
    if (q) { add(dl, kv('Query', q)); }
    add(facts, dl);
    add(box, facts);

    if (codeList(d.kind).length > 1) {
      add(box, el('p', 'stamp', 'Code ' + (S.dtcIndex + 1) + ' of ' + codeList(d.kind).length +
        ' \u2014 left/right steps through the list.'));
    }
  }

  function kv(key, value) {
    var row = el('div', 'kv');
    add(row, el('dt', null, key), el('dd', null, value));
    return row;
  }

  function freezeFrameLine() {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var support = report && report.support ? report.support : null;
    if (!support) { return 'unknown - the scan did not report support'; }
    if (support.freeze_frame === false) { return 'not supported by this ECU (Mode 02)'; }
    if (support.freeze_frame === true) { return 'supported by this ECU'; }
    return 'not reported';
  }

  function queryLine(kind) {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var codes = report && report.codes ? report.codes : null;
    if (!codes || !codes.queries) { return null; }
    var mode = { stored: '03', pending: '07', permanent: '0A' }[kind];
    var q = codes.queries[mode];
    if (!q) { return null; }
    return 'Mode ' + mode + ' \u2192 ' + q.status + (q.supported === false ? ' (not supported)' : '');
  }

  /* ------------------------------------------------------ S5 readiness wall */

  function renderReadiness() {
    var box = $('readinessWall');
    clear(box);
    var report = S.scan && S.scan.report ? S.scan.report : null;
    if (!report || !report.monitors) {
      add(box, el('p', 'empty', 'This scan did not include the readiness wall. Run a full scan.'));
      return;
    }
    var ready = report.readiness || null;
    var diesel = !!(ready && ready.engine_type === 'compression_ignition');
    var head = el('div', 'card verdict');
    head.setAttribute('data-sev', ready ? sevFromVerdict(ready.verdict) : 'info');
    add(head, el('p', 'verdict-headline', ready ? (ready.headline || 'Readiness') : 'Readiness wall'));
    if (ready) {
      add(head, el('p', 'verdict-sub', readinessSentence(ready, report.codes)));
      var rule = ready.rule || {};
      add(head, el('p', 'verdict-rule', 'Rule: ' + (rule.label || 'unknown') +
        ' \u00b7 allowance ' + num(rule.allow_incomplete, 0) +
        ' \u00b7 open within rule ' + num(ready.counted_count, 0) +
        (ready.exempt_incomplete && ready.exempt_incomplete.length
          ? ' \u00b7 excused: ' + ready.exempt_incomplete.map(function (m) { return m.label; }).join(', ')
          : '')));
      if (ready.reasons && ready.reasons.length) {
        add(head, el('p', 'verdict-rule', ready.reasons.join('; ')));
      }
      add(head, el('p', 'verdict-rule', ready.disclaimer || ''));
    }
    add(head, el('p', 'verdict-rule', 'Engine family reported by the ECU: ' +
      (ready && ready.engine_type ? ready.engine_type : 'not reported') +
      (diesel ? ' (diesel / compression ignition copy in use)' : ' (petrol / spark ignition copy in use)')));
    add(box, head);

    ['since_clear', 'this_cycle'].forEach(function (which) {
      var block = report.monitors[which];
      if (!block) { return; }
      var title = which === 'since_clear'
        ? 'Since the codes were cleared'
        : 'Since the engine started (this drive cycle)';
      var wrap = el('div', 'card');
      var label = el('p', 'group-title', title);
      if (block.drive_cycle) { label.textContent = title + ' \u00b7 drive cycle data'; }
      add(wrap, label);
      var meta = el('p', 'stamp', 'MIL ' + (block.mil_on ? 'on' : 'off') +
        ' \u00b7 codes reported by the ECU ' + num(block.dtc_count, 0) +
        ' \u00b7 raw ' + (block.raw_hex || '\u2013'));
      add(wrap, meta);
      if (block.ok === false) {
        add(wrap, el('p', 'empty', 'Not reported: ' + (block.error || block.status)));
      } else {
        add(wrap, monitorRow(groupOf(block, 'common'), true));
        add(wrap, monitorRow(groupOf(block, 'specific'), false));
      }
      add(box, wrap);
    });

    var unsupported = (ready && ready.not_supported) ? ready.not_supported : [];
    if (unsupported.length) {
      var card = el('div', 'card');
      add(card, el('p', 'group-title', 'Not on this car'));
      var line = el('p', 'stamp', unsupported.map(function (m) { return m.label; }).join(', ') +
        ' \u2014 not supported by this ECU, so they never count against the verdict.');
      add(card, line);
      add(box, card);
    }

    var guidance = el('div', 'card');
    add(guidance, el('p', 'group-title', 'How to complete them'));
    add(guidance, el('p', 'stamp', 'General drive-cycle guidance for monitors that are still ' +
      'open \u2014 not ECU-specific instructions.'));
    var open = (ready && ready.incomplete) ? ready.incomplete : [];
    if (!open.length) {
      add(guidance, el('p', 'stamp', 'Nothing to finish: every supported monitor has completed.'));
    } else {
      open.forEach(function (m) {
        var row = el('p', 'stamp');
        add(row, el('b', null, m.label + ': '));
        row.appendChild(document.createTextNode(HINTS[m.key] || HINTS._));
        add(guidance, row);
      });
    }
    var gBtn = el('button', 'btn btn-quiet ctl');
    gBtn.type = 'button';
    gBtn.textContent = S.guidance ? 'Hide drive-cycle guidance' : 'Show drive-cycle guidance';
    gBtn.style.marginTop = '8px';
    gBtn.addEventListener('click', function () { S.guidance = !S.guidance; render(); });
    add(guidance, gBtn);
    if (S.guidance) {
      add(guidance, el('p', 'verdict-sub', COPY.afterClear));
      if (diesel) { add(guidance, el('p', 'verdict-sub', COPY.dieselEgr)); }
      add(guidance, el('p', 'verdict-sub', COPY.driveCycle));
    }
    add(box, guidance);
  }

  function groupOf(block, kind) {
    if (!block) { return []; }
    if (kind === 'common') { return block.common || []; }
    return block.specific || [];
  }

  function monitorRow(monitors, commonKind) {
    var grid = el('div');
    grid.style.display = 'flex';
    grid.style.flexWrap = 'wrap';
    grid.style.gap = '6px';
    monitors.forEach(function (m) {
      var word = MONITOR_WORD[m.state] || { sev: 'quiet', word: m.state, glyph: '\u2013' };
      var wrap = el('span', 'chip chip-sev-' + word.sev);
      wrap.appendChild(document.createTextNode(m.label + ' \u00b7 ' + word.word));
      var hint = commonKind ? null : m.key;
      if (m.state === 'incomplete' && hint && HINTS[hint]) { wrap.title = HINTS[hint]; }
      grid.appendChild(wrap);
    });
    if (!monitors.length) { add(grid, el('p', 'stamp', 'Nothing reported in this group.')); }
    return grid;
  }

  /* ------------------------------------------------------- S6 monitor tests */

  function renderTests() {
    var list = $('mode06');
    clear(list);
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var tests = report ? (report.monitor_tests || []) : [];
    if (!tests.length) {
      var li = el('li');
      add(li, el('p', 'empty', (report && report.support && Object.keys(report.support.obdmid || {}).length)
        ? 'This ECU advertises Mode 06 but reported no monitor tests in this scan.'
        : 'This ECU does not advertise Mode 06 monitor tests, so there is nothing to read here.'));
      list.appendChild(li);
      return;
    }
    tests.forEach(function (rec) {
      var head = el('li');
      var title = el('p', 'row-group', rec.obdmid_name || ('MID ' + rec.obdmid));
      add(title, el('span', 'row-sub', ' \u00b7 ' + num(rec.record_count, 0) + ' record(s)'));
      add(head, title);
      list.appendChild(head);

      if (!rec.ok || !(rec.tests || []).length) {
        var na = el('li');
        add(na, el('p', 'stamp', 'Not answered' +
          (rec.error || rec.status ? ' (' + (rec.error || rec.status) + ')' : '') +
          (rec.advertised ? ' \u00b7 advertised by this ECU.' : ' \u00b7 probed, not advertised by this ECU.')));
        list.appendChild(na);
      }

      (rec.tests || []).forEach(function (t) {
        var key = rec.obdmid + ':' + t.tid;
        var open = !!S.expanded[key];
        var li = el('li');
        var row = el('button', 'row ctl');
        row.type = 'button';
        row.setAttribute('aria-expanded', open ? 'true' : 'false');
        var main = el('div', 'row-main');
        add(main, el('div', 'row-text', t.tid_name || ('TID 0x' + (t.tid || 0).toString(16))));
        var sub = (t.uas_name || '') + ' \u00b7 limits ' + mNum(t.min) + '..' + mNum(t.max) +
          (mKnown(t.value) ? '' : ' \u00b7 unknown scaling') +
          (t.raw_hex && S.raw ? ' \u00b7 raw ' + t.raw_hex : '');
        add(main, el('div', 'row-sub', sub));
        var value = el('div', 'row-value');
        add(value, document.createTextNode(mNum(t.value)));
        if (mKnown(t.value) && t.value.unit) { add(value, el('span', 'row-unit', t.value.unit)); }
        add(row, main, value);
        if (t.within_limits === true) { add(row, chip('ok', '\u2713', 'Within limits')); }
        else if (t.within_limits === false) { add(row, chip('bad', '!', 'Outside limits')); }
        else { add(row, chip('warn', '!', 'Unclear')); }
        row.addEventListener('click', (function (k) {
          return function () { S.expanded[k] = !S.expanded[k]; render(); };
        })(key));
        add(li, row);
        list.appendChild(li);

        if (open) {
          var det = el('li');
          var box = el('div', 'row flat');
          var dmain = el('div', 'row-main');
          add(dmain, el('div', 'row-text', 'Raw record'));
          add(dmain, el('div', 'row-sub', 'raw ' + (t.raw_hex || '\u2013')));
          var raws = 'value raw ' + num(t.value_raw, 0) +
            ' \u00b7 min raw ' + num(t.min_raw, 0) +
            ' \u00b7 max raw ' + num(t.max_raw, 0);
          var note = (t.value && t.value.note) || '';
          add(dmain, el('div', 'row-sub', note ? (raws + ' \u00b7 ' + note) : raws));
          add(box, dmain);
          add(det, box);
          list.appendChild(det);
        }
      });

      if (rec.parse_note || rec.layout_ambiguous) {
        var note = el('li');
        add(note, el('p', 'stamp', rec.parse_note || 'The record layout was ambiguous, so values ' +
          'may be misread \u2014 shown as reported, not as a judgement.'));
        list.appendChild(note);
      }
    });
  }

  /* A Mode 06 value/min/max part: scaled where the table knows the scaling,
   * honest raw int where it does not (unknown UAS) - never a bare dash that
   * reads as "no data" when bytes were actually captured. */
  function mKnown(part) {
    return !!(part && part.scaled !== null && part.scaled !== undefined);
  }

  function mNum(part) {
    if (!part) { return '\u2013'; }
    if (!mKnown(part)) { return 'raw ' + num(part.raw, 0); }
    return num(part.scaled, 0);
  }

  /* ------------------------------------------------------- S9 deep scan */

  /* The freshest full-PID read: a dedicated deep scan wins over the allpids
   * rows cached inside the last full scan; both are the same row shape. */
  function deepSource() {
    if (S.deep && S.deep.rows && S.deep.rows.length) {
      return { rows: S.deep.rows, from: 'deep', at: S.deep.at, duration_s: S.deep.duration_s };
    }
    var report = S.scan && S.scan.report ? S.scan.report : null;
    if (report && report.allpids && report.allpids.length) {
      return { rows: report.allpids, from: 'full', at: S.scanAt, duration_s: S.scan.duration_s };
    }
    return { rows: [], from: null, at: null, duration_s: null };
  }

  function pidHex(pid) {
    return 'PID 0x' + (pid === null || pid === undefined ? '?' : Number(pid).toString(16).toUpperCase());
  }

  function renderDeep() {
    var head = $('deepHead');
    var list = $('deepList');
    clear(head);
    clear(list);
    var src = deepSource();

    if (!src.rows.length) {
      head.setAttribute('data-sev', 'info');
      add(head, el('p', 'verdict-headline', 'No full-PID read yet'));
      add(head, el('p', 'verdict-sub',
        'A deep scan reads every PID this car advertises, one by one. ' +
        'Values the table knows are decoded; the rest stay raw hex; ' +
        'silence stays "no data".'));
      var li = el('li');
      add(li, el('p', 'empty', 'Run a deep scan from the buttons below, or run a full scan - it includes the same read.'));
      list.appendChild(li);
      return;
    }

    var answered = 0, decoded = 0, raw = 0, silent = 0;
    src.rows.forEach(function (r) {
      if (!r.ok) { silent++; }
      else { answered++; if (r.unit) { decoded++; } else { raw++; } }
    });
    head.setAttribute('data-sev', answered ? 'ok' : 'info');
    var h = add(head, el('div', 'verdict-head'));
    add(h, el('p', 'verdict-headline', answered + ' of ' + src.rows.length + ' answered'));
    add(h, chip(answered ? 'ok' : 'info', answered ? '\u2713' : '\u2013',
      silent ? (silent + ' silent') : 'all heard'));
    add(head, el('p', 'verdict-sub',
      (src.from === 'deep' ? 'Deep read' : 'From the last full scan') +
      (src.at ? ' \u00b7 ' + src.at.toLocaleTimeString() : '') +
      (src.duration_s !== null && src.duration_s !== undefined ? ' \u00b7 ' + num(src.duration_s, 1) + ' s' : '') +
      '. Decoded ' + decoded + ' \u00b7 raw ' + raw + ' \u00b7 silent ' + silent + '.' +
      ' Bitmap PIDs (0100, 0120, \u2026) are the support map itself and are read once during discovery, not re-read here.'));

    src.rows.forEach(function (r) {
      var item = el('li');
      var row = el('div', 'row flat');
      var main = el('div', 'row-main');
      var unnamed = /\(unknown\)/.test(r.name || '');
      add(main, el('div', 'row-text', (r.name && !unnamed) ? r.name : pidHex(r.pid)));
      // The value column carries the outcome, so the sub line never repeats
      // it: decoded rows show the raw hex here, raw rows name the gap instead.
      var sub = unnamed ? 'no decoder for this PID' : pidHex(r.pid);
      if (r.ok && r.raw_hex && r.unit) { sub += ' \u00b7 raw ' + r.raw_hex; }
      if (r.ok && !r.unit) { sub += ' \u00b7 unscaled bytes'; }
      if (!r.ok) { sub += ' \u00b7 ' + (r.error || r.status || 'no data'); }
      add(main, el('div', 'row-sub', sub));
      var value = el('div', 'row-value');
      if (!r.ok) {
        add(value, document.createTextNode('no data'));
        value.style.color = 'var(--quiet)';
        value.style.fontSize = '14px';
      } else if (r.unit) {
        add(value, document.createTextNode(num(r.value, 3)));
        add(value, el('span', 'row-unit', r.unit));
      } else {
        add(value, document.createTextNode(r.raw_hex || num(r.value, 0)));
        value.style.fontSize = '14px';
      }
      add(row, main, value);
      add(item, row);
      list.appendChild(item);
    });
    // motion pass: fresh deep rows cross-fade in once per read, not per render
    revealOnce(list, 'deep:' + src.from + ':' + src.rows.length);
  }

  /* ---------------------------------------------------------- S7 identity */

  function renderIdentity() {
    var list = $('identity');
    clear(list);
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var vehicle = report && report.vehicle ? report.vehicle : null;

    function row(label, value, sub) {
      var li = el('li');
      var r = el('div', 'row flat');
      var main = el('div', 'row-main');
      add(main, el('div', 'row-text', label));
      if (sub) { add(main, el('div', 'row-sub', sub)); }
      add(r, main, el('div', 'row-value', value || '\u2013'));
      add(li, r);
      list.appendChild(li);
    }

    if (!vehicle) {
      var li = el('li');
      add(li, el('p', 'empty', 'This scan did not include vehicle identity. Run a full scan.'));
      list.appendChild(li);
      return;
    }

    row('VIN', vehicle.vin || 'not read',
      vehicle.vin ? 'ISO 15765-4 / Mode 09 02' : 'the ECU did not answer Mode 09 02');
    var v = S.vin;
    if (v) {
      if (v.maker) { row('Maker', v.maker, v.maker_source ? ('source: ' + v.maker_source) : ''); }
      if (v.model_year_candidates && v.model_year_candidates.length) {
        row('Model year', v.model_year_candidates.join(' or '),
          'the year code repeats every 30 years on some makers');
      }
      if (v.wmi) { row('World maker id', v.wmi, 'first three VIN characters'); }
      if (v.plant_code) { row('Plant', v.plant_code, ''); }
      if (v.serial) { row('Serial', v.serial, ''); }
      if (v.valid === false) { row('VIN check', 'failed', v.reason || 'the VIN did not validate'); }
    } else if (S.vinState === 'loading') {
      row('Decode', 'reading\u2026', 'offline decode of the VIN');
    } else if (S.vinState === 'error') {
      row('Decode', 'unavailable', 'the backend did not answer /vin');
    }

    row('ECU name', vehicle.ecu_name || 'not read', 'Mode 09 0A');
    row('CALID', vehicle.calid || 'not read', 'calibration id (Mode 09 04)');
    row('CVN', vehicle.cvn || 'not read', 'calibration verification number (Mode 09 06)');
    if (vehicle.obd_standard) {
      row('OBD standard', vehicle.obd_standard.name + ' (' + vehicle.obd_standard.code + ')',
        'reported by PID 01 1C \u00b7 raw ' + (vehicle.obd_standard.raw_hex || '\u2013'));
    }

    var support = report.support || {};
    var pids = support.pids || {};
    var pidCount = Object.keys(pids).reduce(function (n, k) { return n + (pids[k] || []).length; }, 0);
    row('PIDs supported', num(pidCount, 0) + ' across ' + Object.keys(pids).length + ' bitmap(s)',
      Object.keys(pids).join(', ') || 'no PID bitmap was read');
    var mids = support.obdmid || {};
    var midCount = Object.keys(mids).reduce(function (n, k) { return n + (mids[k] || []).length; }, 0);
    row('Mode 06 MIDs', num(midCount, 0),
      Object.keys(mids).join(', ') || 'no OBDMID map was read');
    if (support.infotypes) {
      row('Mode 09 info types', support.infotypes.map(function (i) { return '0x0' + i.toString(16).toUpperCase(); }).join(', '),
        'identity items this ECU answers');
    }
    row('Freeze frame', support.freeze_frame === false ? 'not supported' :
      (support.freeze_frame === true ? 'supported' : 'not reported'), 'Mode 02');

    if (S.vinOnline) {
      var on = S.vinOnline;
      if (on.available && on.fields) {
        Object.keys(on.fields).forEach(function (k) {
          if (!on.fields[k]) { return; }
          row('Online \u00b7 ' + k, on.fields[k], on.source ? 'source: vPIC' : '');
        });
      } else if (on.error) {
        row('Online decode', 'unavailable', on.error);
      }
    }
  }

  function loadVin() {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var vin = report && report.vehicle ? report.vehicle.vin : null;
    if (!vin) { return; }
    if (S.vin) { return; }
    S.vinState = 'loading';
    fetchJSON('/vin?vin=' + encodeURIComponent(vin)).then(function (res) {
      if (res.ok && res.data && res.data.vin) { S.vin = res.data.vin; S.vinState = 'done'; }
      else { S.vinState = 'error'; }
      if (S.screen === 'S7') { render(); }
    });
  }

  function loadOnlineVin() {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var vin = report && report.vehicle ? report.vehicle.vin : null;
    if (!vin) { toast('No VIN in this scan, so there is nothing to decode.', 'warn'); return; }
    toast('Asking the online decoder\u2026', 'info');
    fetchJSON('/vin?vin=' + encodeURIComponent(vin) + '&online=1').then(function (res) {
      if (!res.ok || !res.data || !res.data.vin) {
        toast('Online decode failed: ' + (res.error || 'no answer'), 'warn');
        return;
      }
      S.vinOnline = res.data.vin.online || null;
      S.vin = S.vin || res.data.vin;
      if (S.vinOnline && S.vinOnline.available) {
        toast('Online decode returned ' + Object.keys(S.vinOnline.fields || {}).length + ' field(s).', 'info');
      } else {
        toast('Online decode returned nothing usable' +
          (S.vinOnline && S.vinOnline.error ? ': ' + S.vinOnline.error : '.') +
          ' The offline fields above still stand.', 'warn');
      }
      render();
    });
  }

  /* ------------------------------------------------------------ S8 report */

  function renderReport() {
    var tabs = $('reportTabs');
    clear(tabs);
    ['text', 'csv', 'json'].forEach(function (fmt) {
      var b = el('button', 'tab ctl');
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', S.reportFmt === fmt ? 'true' : 'false');
      b.textContent = fmt.toUpperCase();
      b.addEventListener('click', function () { S.reportFmt = fmt; loadReport(); });
      tabs.appendChild(b);
    });

    var pre = $('reportPre');
    if (S.reportState === 'loading') {
      // motion pass: skeleton lines (opacity pulse) while the lane answers
      pre.classList.remove('reveal-in');
      pre.classList.add('is-loading');
      if (!pre.querySelector('.skel')) {
        pre.textContent = '';
        for (var sk = 0; sk < 4; sk++) {
          var line = el('span', 'skel' + (sk === 3 ? ' short' : ''));
          line.setAttribute('aria-hidden', 'true');
          pre.appendChild(line);
        }
      }
    }
    else if (S.reportState === 'error') {
      pre.classList.remove('is-loading');
      pre.textContent = 'Report unavailable.\n\n' + (S.reportBody || 'The backend did not answer /report.');
      revealOnce(pre, 'report:error:' + (S.reportBody || '').length);
    }
    else if (S.reportBody) {
      pre.classList.remove('is-loading');
      pre.textContent = S.reportBody;
      revealOnce(pre, 'report:done:' + S.reportBody.length);
    }
    else {
      pre.classList.remove('is-loading');
      pre.textContent = COPY.noReport;
    }

    var box = $('settings');
    clear(box);
    box.appendChild(segment('Scan scope', [['full', 'Full'], ['quick', 'Quick']], S.scope, function (v) {
      S.scope = v; store('scope', v); toast('Scan scope: ' + v + '.', 'info'); renderActions(); paintFocus();
    }));
    box.appendChild(segment('Input path', [['auto', 'Auto'], ['bridge', 'Bridge'], ['dom', 'DOM']], S.bridge, function (v) {
      S.bridge = v; store('bridge', v);
      document.body.setAttribute('data-bridge', v);
      toast('Input path: ' + v + ' (now using ' + effectiveBridge() + ').', 'info');
      syncKeyMode(); renderActions(); paintFocus();
    }));
    var note = el('p', 'stamp', COPY.clearCodes);
    box.appendChild(note);
  }

  function segment(label, options, current, onPick) {
    var wrap = el('div', 'seg');
    add(wrap, el('span', null, label + ':'));
    options.forEach(function (pair) {
      var b = el('button', 'tab ctl');
      b.type = 'button';
      b.textContent = pair[1];
      b.setAttribute('aria-selected', current === pair[0] ? 'true' : 'false');
      b.addEventListener('click', function () { if (current !== pair[0]) { onPick(pair[0]); } });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function loadReport() {
    S.reportState = 'loading';
    render();
    fetchJSON('/report?format=' + encodeURIComponent(S.reportFmt)).then(function (res) {
      if (!res.ok) {
        S.reportState = 'error';
        S.reportBody = res.error || ('HTTP ' + res.status);
        toast('Report unavailable: ' + S.reportBody, 'warn');
      } else if (S.reportFmt === 'json') {
        S.reportState = 'done';
        try {
          S.reportBody = JSON.stringify(res.data, null, 2);
        } catch (err) {
          S.reportBody = res.raw || '';
        }
      } else {
        S.reportState = 'done';
        S.reportBody = res.raw || '';
      }
      if (S.screen === 'S8') { render(); }
    });
  }

  function downloadName() {
    var report = S.scan && S.scan.report ? S.scan.report : null;
    var vin = report && report.vehicle ? report.vehicle.vin : null;
    var d = new Date();
    var stamp = d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '-' +
      pad(d.getHours()) + pad(d.getMinutes());
    var tail = vin ? vin.slice(-7) : 'no-vin';
    var ext = S.reportFmt === 'json' ? 'json' : (S.reportFmt === 'csv' ? 'csv' : 'txt');
    return 'diag-report-' + stamp + '-' + tail + '.' + ext;
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /* ------------------------------------------------- S10 compatibility */

  /* The sheet is built backend-side from the last finished report without
   * touching the car, so this screen is a read plus two export actions. */
  function loadCap() {
    if (S.capState === 'loading') { return; }
    S.capState = 'loading';
    if (S.screen === 'S10') { render(); }
    fetchJSON('/capability').then(function (res) {
      if (res.ok && res.data && res.data.sheet) {
        S.cap = res.data;
        S.capState = 'text';
        if (S.screen === 'S10') { render(); }
        fetch('/capability?format=text', { cache: 'no-store', headers: { 'Accept': 'text/plain' } })
          .then(function (r2) { return r2.text(); })
          .then(function (body) {
            S.capText = body;
            S.capState = 'done';
            if (S.screen === 'S10') { render(); }
          })
          .catch(function () {
            S.capState = 'done';
            if (S.screen === 'S10') { render(); }
          });
      } else {
        S.capState = 'error';
        S.cap = null;
        toast('Compatibility sheet unavailable: ' + (res.error || 'no answer'), 'warn');
        if (S.screen === 'S10') { render(); }
      }
    });
  }

  function capModeChip(state) {
    if (state === 'answered') { return chip('ok', '\u2713', 'answers'); }
    if (state === 'not-supported') { return chip('quiet', '\u2013', 'not on this car'); }
    return chip('quiet', '\u2013', 'not probed');
  }

  function renderCompat() {
    var wrap = $('compatWrap');
    clear(wrap);
    if (S.capState === 'idle' && !S.cap) { loadCap(); return; }
    if (S.capState === 'loading' && !S.cap) {
      add(wrap, el('p', 'empty', 'Reading the compatibility sheet\u2026'));
      return;
    }
    if (!S.cap) {
      add(wrap, el('p', 'empty',
        'No compatibility sheet yet. Run a scan first - the sheet is built from the last finished report.'));
      return;
    }
    var cap = S.cap;

    var top = el('div', 'card verdict');
    top.setAttribute('data-sev', 'info');
    var h = add(top, el('div', 'verdict-head'));
    add(h, el('p', 'verdict-headline', 'This car, this app'));
    add(h, chip('info', '\u2013', cap.data_source === 'replay' ? 'replay data' : 'live data'));
    var cov = cap.coverage || {};
    add(top, el('p', 'verdict-sub',
      'App v' + (cap.app_version || '?') +
      (cov.full ? ' \u00b7 full scan' : ' \u00b7 partial scan (' + ((cov.sections || []).join(', ') || '?') + ')') +
      (cov.queries !== null && cov.queries !== undefined ? ' \u00b7 ' + cov.queries + ' queries' : '') +
      (cap.generated_at ? ' \u00b7 ' + cap.generated_at : '')));
    add(wrap, top);

    var pid = cap.pid_support || {};
    var pidCard = el('div', 'card');
    add(pidCard, el('p', 'group-title', 'Mode 01 PID support (' + (pid.total || 0) + ' advertised)'));
    (pid.banks || []).forEach(function (b) {
      var row = el('div', 'kv');
      add(row, el('dt', null, b.bank + ' [' + (b.bitmap_hex || '?') + ']'),
        el('dd', null, b.pids_hex || '-'));
      add(pidCard, row);
    });
    if (!(pid.banks || []).length) { add(pidCard, el('p', 'stamp', 'Not probed in this scan.')); }
    add(wrap, pidCard);

    var m = cap.mode06 || {};
    var mCard = el('div', 'card');
    var answered = m.answered || [], unanswered = m.unanswered || [];
    add(mCard, el('p', 'group-title', 'Mode 06 monitors (' + answered.length + ' answered)'));
    answered.concat(unanswered).forEach(function (r) {
      var row = el('div', 'kv');
      var label = 'MID ' + (r.obdmid_hex || '?');
      var detail = (r.name || 'unknown') +
        (r.answered ? ' \u00b7 ' + r.tests + ' test(s)' + (r.advertised ? '' : ' \u00b7 probed, not advertised')
          : ' \u00b7 not answered');
      add(row, el('dt', null, label), el('dd', null, detail));
      add(mCard, row);
    });
    if (!answered.length && !unanswered.length) {
      add(mCard, el('p', 'stamp', 'The mode06 phase did not run in this scan.'));
    }
    add(wrap, mCard);

    var modes = cap.modes || {};
    var order = ['01', '02', '03', '05', '06', '07', '09', '0A'];
    var modeCard = el('div', 'card');
    add(modeCard, el('p', 'group-title', 'Mode support, as observed'));
    order.forEach(function (k) {
      var info = modes[k] || {};
      var row = el('div', 'kv');
      row.style.alignItems = 'center';
      var dd = el('dd', null, info.note || info.state || '?');
      dd.style.flex = '1 1 auto';
      add(row, el('dt', null, 'Mode ' + k), dd, capModeChip(info.state));
      add(modeCard, row);
    });
    add(modeCard, el('p', 'stamp', 'Readiness monitors read: ' + (cap.readiness_seen ? 'yes' : 'no') + '.'));
    add(wrap, modeCard);

    var id = cap.identity || {};
    var std = id.obd_standard || {};
    var idCard = el('div', 'card');
    add(idCard, el('p', 'group-title', 'Vehicle / ECU identity'));
    [['VIN', id.vin], ['ECU name', id.ecu_name], ['CALID', id.calid],
     ['CVN', id.cvn], ['OBD standard', std.name]].forEach(function (pair) {
      var row = el('div', 'kv');
      add(row, el('dt', null, pair[0]), el('dd', null, pair[1] || 'not reported'));
      add(idCard, row);
    });
    add(idCard, el('p', 'stamp', 'Only what the car reported - blanks are the ECU staying silent, not this app failing.'));
    add(wrap, idCard);

    var preTitle = el('p', 'group-title', 'Sheet text (paste into a GitHub issue as-is)');
    add(wrap, preTitle);
    var pre = el('pre', 'report scroll');
    pre.textContent = S.capText ||
      (S.capState === 'text' ? 'Fetching the paste-ready text\u2026' : 'Sheet text unavailable - the rows above still stand.');
    add(wrap, pre);
  }

  function copyCapText() {
    var text = S.capText || '';
    if (!text) { toast('Sheet text is not ready yet - give it a second.', 'warn'); return; }
    function done() { toast('Compatibility sheet copied - paste it into a GitHub issue.', 'info'); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      if (document.execCommand('copy')) { done(); }
      else { toast('Copy failed - use Download instead.', 'warn'); }
    } catch (err) {
      toast('Copy failed - use Download instead.', 'warn');
    }
    document.body.removeChild(ta);
  }

  function compatName() {
    var d = new Date();
    return 'hudiy-compat-' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '-' +
      pad(d.getHours()) + pad(d.getMinutes()) + '.txt';
  }

  /* ------------------------------------------------- S11 clear fault codes */

  /* Mode 04 two-screen confirm flow (docs/FEATURE_SURVEY_FINDINGS.md section 5:
   * screen 1 = consequence list + fix-first checkbox, screen 2 = result +
   * readiness-incomplete follow-up). Seam contract: POST /clear?confirm=yes;
   * {ok, status, mode04_positive, duration_s, codes_seen_before, followup,
   * [permanent_codes_note]}; 400 missing confirm, 409 already clearing,
   * 502 not confirmed cleared. confirm travels as a query parameter, like
   * every other argument on this backend (/scan?sections=, /report?format=).
   * Single-flight: S.clearBusy guards the POST, the backend 409s the rest. */

  var CLEAR_TIMEOUT_MS = 30000;

  function clearTimeoutMs() {
    // Bench hook only: ?clearTimeoutMs= shortens the wait so the smoke test
    // can exercise the timeout path without stalling 30 s.
    var q = param('clearTimeoutMs');
    var n = q ? parseInt(q, 10) : NaN;
    return (n > 0) ? n : CLEAR_TIMEOUT_MS;
  }

  function laneOnline() {
    return !!(S.health && S.health.obd && S.health.obd.state === 'online');
  }

  function clearCounts() {
    return {
      stored: codeList('stored').length,
      pending: codeList('pending').length,
      permanent: codeList('permanent').length
    };
  }

  function openClear() {
    if (!laneOnline()) { toast(COPY.clearOffline, 'warn'); return; }
    if (S.clearBusy) { toast(COPY.clearBusy, 'warn'); return; }
    S.clear = { stage: 'confirm', checked: false, result: null, error: null,
                guide: false, rereading: false, timedOut: false,
                cancelled: false, at: null };
    go('S11');
  }

  function renderClear() {
    var wrap = $('clearWrap');
    clear(wrap);
    if (!S.clear) { S.clear = { stage: 'confirm', checked: false, result: null, error: null, guide: false, rereading: false }; }
    if (S.clear.stage === 'done') { renderClearDone(wrap); }
    else if (S.clear.stage === 'working') { renderClearWorking(wrap); }
    else { renderClearConfirm(wrap); }
  }

  function clearHead(wrap, sev, headline) {
    var card = el('div', 'card verdict');
    card.id = 'clearCard';
    card.setAttribute('data-sev', sev);
    add(card, el('p', 'verdict-headline', headline));
    add(wrap, card);
    return card;
  }

  function renderClearConfirm(wrap) {
    var counts = clearCounts();
    var total = counts.stored + counts.pending + counts.permanent;
    var card = clearHead(wrap, 'warn',
      total ? ('Clear ' + total + ' fault code' + (total === 1 ? '' : 's') + '?')
            : 'Clear fault codes?');
    add(card, el('p', 'verdict-sub', COPY.clearLead));
    var list = el('ul', 'clear-list');
    COPY.clearEffects.forEach(function (line) {
      add(list, el('li', 'verdict-sub', line));
    });
    add(card, list);
    // Permanent-code honesty line: the last scan still holds some, or the
    // last clear/scan context carried the note - either way no tool clears
    // those; only the ECU does. (Never battery-disconnect advice: survey
    // section 5 rule 3.)
    if (counts.permanent > 0 || (S.clear.result && S.clear.result.permanent_codes_note)) {
      add(card, el('p', 'verdict-sub', COPY.permanent));
    }
    if (S.clear.result && S.clear.result.permanent_codes_note && counts.permanent === 0) {
      add(card, el('p', 'verdict-sub', S.clear.result.permanent_codes_note));
    }
    // Fix-first checkbox: a wrapping label is the .ctl (one focus stop, not
    // two). label.click() forwards to the input, so knob/shim 'activate',
    // keyboard space/enter and touch all toggle through the same 'change'
    // event with no double-toggle.
    var row = el('label', 'check-row ctl');
    var box = document.createElement('input');
    box.type = 'checkbox';
    box.id = 'clearFixFirst';
    box.checked = !!S.clear.checked;
    box.addEventListener('change', function () {
      S.clear.checked = box.checked;
      renderActions();
      paintFocus();
    });
    row.appendChild(box);
    add(row, el('span', null, COPY.clearFixFirst));
    add(card, row);
    var meta = el('p', 'stamp', counts.stored + ' stored \u00b7 ' + counts.pending +
      ' pending \u00b7 ' + counts.permanent + ' permanent \u00b7 ' +
      'from the last scan' + (S.scanAt ? ' (' + S.scanAt.toLocaleTimeString() + ')' : ''));
    add(wrap, meta);
  }

  function renderClearWorking(wrap) {
    var card = el('div', 'card card-scan');
    card.id = 'clearCard';
    var top = el('div', 'scan-top');
    var mark = el('span', 'scan-mark is-busy');
    mark.setAttribute('aria-hidden', 'true');
    add(top, mark);
    var label = el('p', 'scan-label is-scanning', COPY.clearWorking + '\u2026');
    add(top, label);
    add(card, top);
    add(card, el('p', 'scan-note',
      'The diagnostics lane is single-flight: nothing else can query the ECU ' +
      'until this finishes. Cancelling stops the wait here, not the ECU.'));
    add(wrap, card);
  }

  function renderClearDone(wrap) {
    var res = S.clear.result || {};
    var card = el('div', 'card verdict');
    card.id = 'clearCard';
    card.setAttribute('data-sev', 'ok');
    var top = el('div', 'scan-top');
    var mark = el('span', 'scan-mark is-done');
    mark.setAttribute('aria-hidden', 'true');
    add(top, mark);
    add(top, el('p', 'scan-label', COPY.clearDoneHead));
    add(card, top);
    var seen = (res.codes_seen_before !== undefined && res.codes_seen_before !== null)
      ? num(res.codes_seen_before, 0) : '\u2013';
    add(card, el('p', 'verdict-sub',
      COPY.clearDoneHead + ': ' + seen + ' code(s) held before the reset' +
      (res.duration_s !== undefined && res.duration_s !== null
        ? ' \u00b7 confirmed in ' + num(res.duration_s, 1) + ' s' : '') + '.'));
    if (res.permanent_codes_note) {
      add(card, el('p', 'verdict-sub', res.permanent_codes_note));
    } else if (clearCounts().permanent > 0) {
      add(card, el('p', 'verdict-sub', COPY.permanent));
    }
    add(wrap, card);

    var follow = el('div', 'card');
    add(follow, el('p', 'group-title', COPY.clearFollowTitle));
    if (res.followup && res.followup.message) {
      add(follow, el('p', 'verdict-sub', res.followup.message));
    }
    add(follow, el('p', 'verdict-sub', COPY.afterClear));
    // The honest proof the reset landed: the wall re-read automatically
    // after the clear, so the all-incomplete state is shown, not claimed.
    if (S.clear.rereading) {
      add(follow, el('p', 'stamp', COPY.clearReread));
    } else if (S.clear.reread) {
      add(follow, el('p', 'stamp', S.clear.reread));
    }
    var gBtn = el('button', 'btn btn-quiet ctl');
    gBtn.type = 'button';
    gBtn.textContent = S.clear.guide ? COPY.clearGuideHide : COPY.clearGuideShow;
    gBtn.style.marginTop = '8px';
    gBtn.addEventListener('click', function () { S.clear.guide = !S.clear.guide; render(); });
    add(follow, gBtn);
    if (S.clear.guide) {
      add(follow, el('p', 'verdict-sub', COPY.driveCycle));
    }
    add(wrap, follow);
    revealOnce(follow, 'clear:done:' + (S.clear.at || 0));
  }

  function clearServerMessage(res) {
    if (res && res.data && (res.data.message || res.data.error)) {
      return res.data.message || res.data.error;
    }
    if (res && res.error) { return res.error; }
    return 'HTTP ' + (res ? res.status : '?');
  }

  function postClear() {
    if (S.clearBusy) { toast(COPY.clearBusy, 'warn'); return; }
    if (!S.clear || !S.clear.checked) { return; }
    if (!laneOnline()) { toast(COPY.clearOffline, 'warn'); return; }
    S.clearBusy = true;
    S.clear.stage = 'working';
    S.clear.timedOut = false;
    S.clear.cancelled = false;
    S.clear.result = null;
    render();
    var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
    S.clearAbort = ctrl;
    var timer = window.setTimeout(function () {
      if (S.clear) { S.clear.timedOut = true; }
      if (ctrl) { try { ctrl.abort(); } catch (err) { /* already settled */ } }
    }, clearTimeoutMs());
    var opts = { method: 'POST', cache: 'no-store', headers: { 'Accept': 'application/json' } };
    if (ctrl) { opts.signal = ctrl.signal; }
    fetch('/clear?confirm=yes', opts)
      .then(function (res) {
        return res.text().then(function (body) {
          var data = null;
          try { data = JSON.parse(body); } catch (err) { data = null; }
          return { ok: res.ok, status: res.status, data: data, raw: body,
                   error: res.ok ? null : ('HTTP ' + res.status) };
        });
      })
      .then(function (res) { finishClear(res, timer); })
      .catch(function (err) {
        finishClear({ ok: false, status: 0, data: null, raw: '',
                      error: (err && err.name === 'AbortError') ? 'aborted' : 'network error' }, timer);
      });
  }

  function cancelClear() {
    if (!S.clearBusy) { return; }
    if (S.clear) { S.clear.cancelled = true; }
    if (S.clearAbort) { try { S.clearAbort.abort(); } catch (err) { /* already settled */ } }
  }

  function finishClear(res, timer) {
    if (timer) { window.clearTimeout(timer); }
    S.clearAbort = null;
    S.clearBusy = false;
    if (!S.clear) { return; }
    var card = function () { return $('clearCard'); };
    if (S.clear.cancelled) {
      S.clear.cancelled = false;
      S.clear.stage = 'confirm';
      toast(COPY.clearCancelled, 'warn');
      if (S.screen === 'S11') { render(); }
      return;
    }
    if (S.clear.timedOut || (res && !res.ok && res.status === 0 && res.error === 'aborted')) {
      S.clear.timedOut = false;
      S.clear.stage = 'confirm';
      toast(COPY.clearTimeout, 'bad');
      if (S.screen === 'S11') { render(); shakeOnce(card()); }
      return;
    }
    if (!res || !res.ok || !res.data || res.data.ok === false) {
      var msg = clearServerMessage(res);
      S.clear.stage = 'confirm';
      if (res && res.status === 409) {
        // Contention, not a verdict on the car: snackbar only, no shake.
        toast(msg, 'warn');
      } else {
        toast('Clear failed: ' + msg, 'bad');
      }
      if (S.screen === 'S11') { render(); }
      if (!(res && res.status === 409)) { shakeOnce(card()); }
      return;
    }
    S.clear.result = res.data;
    S.clear.stage = 'done';
    S.clear.at = Date.now();
    S.clear.reread = null;
    toast(COPY.clearDoneHead + (res.data.duration_s !== undefined && res.data.duration_s !== null
      ? ' in ' + num(res.data.duration_s, 1) + ' s.' : '.'), 'info');
    if (S.screen === 'S11') { render(); }
    markClearDone();
    rereadAfterClear();
  }

  // Proof the reset landed: re-read codes + readiness and merge them into
  // the cached report, so S3/S5 show the post-clear state instead of stale
  // pre-clear rows. Never clobbers identity/Mode 06/deep sections.
  function rereadAfterClear() {
    if (!S.clear) { return; }
    S.clear.rereading = true;
    if (S.screen === 'S11') { render(); }
    fetchJSON('/scan?sections=' + QUICK.join(',')).then(function (res) {
      if (!S.clear) { return; }
      S.clear.rereading = false;
      if (res.ok && res.data && res.data.report) {
        var fresh = res.data.report;
        if (S.scan && S.scan.report) {
          if (fresh.codes) { S.scan.report.codes = fresh.codes; }
          if (fresh.monitors) { S.scan.report.monitors = fresh.monitors; }
          if (fresh.readiness) { S.scan.report.readiness = fresh.readiness; }
        }
        var codes = fresh.codes || {};
        var open = (fresh.readiness && fresh.readiness.incomplete)
          ? fresh.readiness.incomplete.length : null;
        S.clear.reread = 'Readiness re-read' +
          (res.data.duration_s !== undefined && res.data.duration_s !== null
            ? ' (' + num(res.data.duration_s, 1) + ' s)' : '') + ': ' +
          (((codes.stored || []).length) + ' stored code(s) \u00b7 ' +
          (open === null ? 'readiness wall updated' : (open + ' monitor(s) Not ready')));
      } else {
        toast(COPY.clearRereadFail, 'warn');
      }
      if (S.screen === 'S11') { render(); }
    });
  }

  // Motion twins of syncScanMotion/markScanDone for the S11 status row: the
  // SAME classes (.scan-mark/.is-busy/.is-done, .scan-label/.swap-in) and
  // the SAME helpers (swapText), so no new animation exists to audit.
  function syncClearMotion() {
    var label = document.querySelector('#clearWrap .scan-label');
    if (label) { swapText(label, COPY.clearWorking + '\u2026'); }
  }

  function markClearDone() {
    var mark = document.querySelector('#clearWrap .scan-mark');
    if (mark) { mark.classList.remove('is-busy'); mark.classList.add('is-done'); }
    var label = document.querySelector('#clearWrap .scan-label');
    if (label) { label.classList.remove('is-scanning'); swapText(label, COPY.clearDoneHead); }
  }

  /* ------------------------------------------------------------- actions */

  function button(label, cls, onTap, enabled) {
    var b = el('button', 'btn ctl ' + (cls || ''), label);
    b.type = 'button';
    if (enabled === false) { b.disabled = true; }
    b.addEventListener('click', onTap);
    return b;
  }

  function renderActions() {
    var bar = $('actions');
    clear(bar);
    var done = !!(S.scan && S.scan.report);
    var plan = [];

    if (S.screen === 'S0') {
      plan.push(button(S.scan ? 'Scan again' : 'Start health scan', 'btn-primary', startScan));
      if (S.scan) { plan.push(button('Open report', '', function () { go('S8'); loadReport(); })); }
      if (S.scan) { plan.push(button('Health summary', '', function () { go('S2'); })); }
      plan.push(el('span', 'grow'));
      plan.push(button('Exit', '', exitOverlay));
    } else if (S.screen === 'S1') {
      // Cancel must be live exactly while a scan is in flight - it is the only
      // way out of S1 (the footer button is the sole cancel affordance).
      plan.push(button('Cancel', '', cancelScan, !!S.busy));
      plan.push(el('span', 'grow'));
      if (!S.busy && S.degraded) { plan.push(button('Retry', 'btn-primary', startScan)); }
    } else if (S.screen === 'S2') {
      plan.push(button('Scan again', 'btn-primary', startScan));
      plan.push(button('Fault codes', '', function () { go('S3'); }, done));
      plan.push(button('Deep scan', '', startDeepScan));
      plan.push(button('Report', '', function () { go('S8'); loadReport(); }));
    } else if (S.screen === 'S3') {
      plan.push(button('Health summary', '', function () { go('S2'); }));
      // Mode 04 entry: gated on the live lane, never on cached state. A dead
      // link means the ECU cannot confirm a reset, so the button stays inert.
      plan.push(button('Clear fault codes', 'btn-primary', openClear, laneOnline()));
      plan.push(el('span', 'grow'));
      plan.push(el('span', 'note', codeList(S.dtcTab).length + ' ' + S.dtcTab + ' code(s)'));
    } else if (S.screen === 'S4') {
      plan.push(button('Back to codes', 'btn-primary', function () { go('S3'); }));
      plan.push(el('span', 'grow'));
      plan.push(el('span', 'note', 'left/right steps through codes'));
    } else if (S.screen === 'S5') {
      plan.push(button('Health summary', 'btn-primary', function () { go('S2'); }));
      plan.push(button(S.guidance ? 'Hide guidance' : 'Drive-cycle guidance', '',
        function () { S.guidance = !S.guidance; render(); }));
    } else if (S.screen === 'S6') {
      plan.push(button('Health summary', 'btn-primary', function () { go('S2'); }));
      plan.push(button(S.raw ? 'Hide raw values' : 'Show raw values', '',
        function () { S.raw = !S.raw; render(); }));
    } else if (S.screen === 'S7') {
      plan.push(button('Health summary', 'btn-primary', function () { go('S2'); }));
      plan.push(button('Decode VIN online', '', loadOnlineVin, !!(S.scan && S.scan.report && S.scan.report.vehicle && S.scan.report.vehicle.vin)));
    } else if (S.screen === 'S8') {
      // Ungated on purpose: after a page reload the backend still holds the
      // last report while S.scan is empty - both targets explain themselves.
      plan.push(button('Health summary', 'btn-primary', function () { go('S2'); }));
      plan.push(button('Compatibility', '', function () { go('S10'); loadCap(); }));
      var a = el('a', 'btn ctl', 'Download ' + S.reportFmt.toUpperCase());
      a.href = '/report?format=' + encodeURIComponent(S.reportFmt);
      a.setAttribute('download', downloadName());
      a.style.textDecoration = 'none';
      a.style.display = 'inline-flex';
      a.style.alignItems = 'center';
      plan.push(a);
    } else if (S.screen === 'S9') {
      plan.push(button('Run deep scan', 'btn-primary', startDeepScan));
      plan.push(button('Health summary', '', function () { go('S2'); }, done));
      plan.push(el('span', 'grow'));
      var src = deepSource();
      plan.push(el('span', 'note', src.rows.length
        ? (src.rows.filter(function (r) { return r.ok; }).length + ' of ' + src.rows.length + ' answered')
        : 'no PID rows yet'));
    } else if (S.screen === 'S10') {
      plan.push(button('Copy sheet', 'btn-primary', copyCapText, !!(S.capText)));
      var c = el('a', 'btn ctl', 'Download .txt');
      c.href = '/capability?format=text';
      c.setAttribute('download', compatName());
      c.style.textDecoration = 'none';
      c.style.display = 'inline-flex';
      c.style.alignItems = 'center';
      plan.push(c);
      plan.push(el('span', 'grow'));
      plan.push(el('span', 'note', 'paste into a GitHub issue'));
    } else if (S.screen === 'S11') {
      var stage = S.clear ? S.clear.stage : 'confirm';
      if (stage === 'working') {
        plan.push(button('Cancel', '', cancelClear, true));
        plan.push(el('span', 'grow'));
        plan.push(el('span', 'note', COPY.clearWorking + '\u2026'));
      } else if (stage === 'done') {
        plan.push(button(COPY.clearBack, '', function () { go('S3'); }));
        plan.push(button('Readiness wall', 'btn-primary', function () { go('S5'); }, !!(S.scan && S.scan.report)));
        plan.push(el('span', 'grow'));
        plan.push(el('span', 'note', 'monitors reset'));
      } else {
        plan.push(button(COPY.clearBack, '', function () { go('S3'); }));
        plan.push(el('span', 'grow'));
        plan.push(button(COPY.clearClearNow, 'btn-danger',
          postClear, !!(S.clear && S.clear.checked) && !S.clearBusy));
      }
    }

    plan.forEach(function (n) { bar.appendChild(n); });
    return bar;
  }

  /* ---------------------------------------------------------------- focus */

  function controls() {
    var root = screenEl();
    if (!root) { return []; }
    var all = Array.prototype.slice.call(root.querySelectorAll('.ctl'));
    /* The action buttons live in the GLOBAL #actions bar, not inside the
     * .screen sections (renderActions), so the ring must merge them or every
     * bar button is unreachable - on S0 the screen section alone has zero
     * controls and nav silently no-ops (same fix the wheel hook got 11 Sep).
     * Order mirrors __diagKeyNav: screen controls, then bar, then top-bar
     * Back. */
    var bar = document.getElementById('actions');
    if (bar) { all = all.concat(Array.prototype.slice.call(bar.querySelectorAll('.ctl'))); }
    var backBtn = document.getElementById('back');
    if (backBtn && !backBtn.hidden) { all.push(backBtn); }
    var out = [];
    for (var i = 0; i < all.length; i++) {
      var n = all[i];
      if (n.disabled) { continue; }
      if (n.offsetParent === null && n.tagName !== 'A') { continue; }
      out.push(n);
    }
    return out;
  }

  function paintFocus() {
    var nodes = document.querySelectorAll('.focused');
    for (var i = 0; i < nodes.length; i++) { nodes[i].classList.remove('focused'); }
    var list = controls();
    if (!list.length) { S.focus = 0; return; }
    if (S.focus >= list.length) { S.focus = list.length - 1; }
    if (S.focus < 0) { S.focus = 0; }
    list[S.focus].classList.add('focused');
  }

  function scrollBox() {
    var root = screenEl();
    return root ? root.querySelector('.scroll') : null;
  }

  function moveFocus(delta) {
    var list = controls();
    if (!list.length) { return false; }
    var next = S.focus + delta;
    if (next >= 0 && next < list.length) {
      S.focus = next;
      paintFocus();
      var node = list[S.focus];
      if (node.scrollIntoView) { node.scrollIntoView({ block: 'nearest' }); }
      return true;
    }
    var box = scrollBox();
    if (box && box.scrollHeight > box.clientHeight + 4) {
      box.scrollTop = box.scrollTop + delta * 56;
      return true;
    }
    return false;
  }

  function horizontal(dir) {
    if (S.screen === 'S3') { return cycleTab(['stored', 'pending', 'permanent'], dir, function (v) { S.dtcTab = v; S.dtcIndex = 0; }); }
    if (S.screen === 'S8') { return cycleTab(['text', 'csv', 'json'], dir, function (v) { S.reportFmt = v; loadReport(); }); }
    if (S.screen === 'S4') {
      var entries = codeList(S.dtcTab);
      if (entries.length < 2) { return false; }
      var next = S.dtcIndex + dir;
      if (next < 0 || next >= entries.length) { return false; }
      openDetail(next);
      return true;
    }
    return false;
  }

  function cycleTab(order, dir, apply) {
    var current = S.screen === 'S3' ? S.dtcTab : S.reportFmt;
    var idx = order.indexOf(current);
    var next = idx + dir;
    if (next < 0 || next >= order.length) { return false; }
    apply(order[next]);
    if (S.screen === 'S3') { render(); }
    return true;
  }

  function activate() {
    var list = controls();
    var node = list[S.focus];
    if (node) { node.click(); }
    return true;
  }

  function back() {
    // At the home screen Back means "leave": hide the overlay (Hudiy provides no
    // close of its own, so this is the only exit from a custom overlay).
    if (S.screen === 'S0') { return exitOverlay(); }
    var target = PARENT[S.screen] || 'S0';
    return go(target);
  }

  /* --------------------------------------------------------- leaving the app */

  // A Hudiy custom overlay stays up until its client hides it - the page can
  // never close itself. The backend owns the control lane (it registered the
  // menu action), so we ask it to hide us, then tear our own DOM down so the
  // car shows through even if the ask never landed.
  var leaving = false;

  function exitOverlay() {
    if (leaving) { return true; }
    leaving = true;
    stopPolling();
    try {
      fetch('/ui/hide', { method: 'POST', cache: 'no-store', headers: { 'Accept': 'application/json' } })
        .catch(function () { /* the overlay must drop even with the backend down */ })
        .then(hideOwnDom);
    } catch (err) { hideOwnDom(); }
    window.setTimeout(hideOwnDom, 400);  // belt: never hang on a stuck fetch
    return true;
  }

  function hideOwnDom() {
    document.body.classList.add('exited');
    var app = $('app');
    if (app) { app.hidden = true; }
    var toast = $('toast');
    if (toast) { toast.hidden = true; }
  }

  /* ------------------------------------------------------- input: bridge */

  window.hudiy = window.hudiy || {};
  var H = window.hudiy;

  H.onAttached = function () {
    S.attached = true;
    /* Relaunch after Exit = Hudiy RE-SHOWS the singleton webview; onAttached
     * is the one reliable signal of that. Without this, body.exited + hidden
     * #app persist and the relaunch paints blank (found live 11 Sep). */
    document.body.classList.remove('exited');
    leaving = false;
    var unhide = $('app');
    if (unhide) { unhide.hidden = false; }
    document.body.setAttribute('data-bridge', effectiveBridge());
    syncKeyMode();
    startPolling();
  };

  H.onInputFocusChanged = function () { syncKeyMode(); };
  H.onActivatedChanged = function () {
    syncKeyMode();
    /* Never hard-stop polling on `activated` (unreliable on this build);
     * restartPolling() re-evaluates the real gate (page visibility). */
    restartPolling();
  };
  H.onColorSchemeChanged = function () { applyScheme(); };
  H.onMoveToNextControl = function () { return bridgeActive() ? moveFocus(1) : true; };
  H.onMoveToPreviousControl = function () { return bridgeActive() ? moveFocus(-1) : true; };
  H.onTriggered = function () { if (bridgeActive()) { activate(); } };
  H.onGoLeft = function () { return bridgeActive() ? horizontal(-1) : true; };
  H.onGoRight = function () { return bridgeActive() ? horizontal(1) : true; };
  H.onGoBack = function () { return bridgeActive() ? back() : true; };
  H.onDetached = function () { S.attached = false; stopPolling(); };

  function bridgeActive() {
    return effectiveBridge() === 'bridge' && S.attached && H.inputFocus !== false;
  }

  function syncKeyMode() {
    var on = false;
    if (effectiveBridge() === 'bridge') { on = !!(H.inputFocus && H.activated); }
    else { on = S.kb; }
    document.body.classList.toggle('kb', on);
    if (!on && effectiveBridge() === 'bridge') {
      var nodes = document.querySelectorAll('.focused');
      for (var i = 0; i < nodes.length; i++) { nodes[i].classList.remove('focused'); }
    } else if (on) {
      paintFocus();
    }
  }

  /* Material 3 scheme consumption (docs/M3_UI_RESEARCH.md sections 1.3/4.2/4.3).
   * Every camelCase token on hudiy.colorScheme maps to a --m3-kebab-case CSS
   * custom property; diag.css binds its legacy vars (--ok/--warn/--bad/--info,
   * --bg/--panel/--line/--ink/...) to those custom properties with the
   * Okabe-Ito fallback scheme as static values, so the page renders correctly
   * with or without the Hudiy bridge (TEST-BOTH-PATHS). Only tokens that are
   * present get written; each set re-derives the translucent severity tints.
   * Palette-key colors (primaryPaletteKeyColor etc.) are seed swatches, NOT
   * presentation colors — deliberately not mapped. */
  var M3_CSS_BY_HUDIY = {
    background: "--m3-background",
    onBackground: "--m3-on-background",
    surface: "--m3-surface",
    onSurface: "--m3-on-surface",
    surfaceDim: "--m3-surface-dim",
    surfaceBright: "--m3-surface-bright",
    surfaceContainerLowest: "--m3-surface-container-lowest",
    surfaceContainerLow: "--m3-surface-container-low",
    surfaceContainer: "--m3-surface-container",
    surfaceContainerHigh: "--m3-surface-container-high",
    surfaceContainerHighest: "--m3-surface-container-highest",
    surfaceVariant: "--m3-surface-variant",
    onSurfaceVariant: "--m3-on-surface-variant",
    inverseSurface: "--m3-inverse-surface",
    inverseOnSurface: "--m3-inverse-on-surface",
    inversePrimary: "--m3-inverse-primary",
    outline: "--m3-outline",
    outlineVariant: "--m3-outline-variant",
    shadow: "--m3-shadow",
    scrim: "--m3-scrim",
    surfaceTint: "--m3-surface-tint",
    primary: "--m3-primary",
    onPrimary: "--m3-on-primary",
    primaryContainer: "--m3-primary-container",
    onPrimaryContainer: "--m3-on-primary-container",
    secondary: "--m3-secondary",
    onSecondary: "--m3-on-secondary",
    secondaryContainer: "--m3-secondary-container",
    onSecondaryContainer: "--m3-on-secondary-container",
    tertiary: "--m3-tertiary",
    onTertiary: "--m3-on-tertiary",
    tertiaryContainer: "--m3-tertiary-container",
    onTertiaryContainer: "--m3-on-tertiary-container",
    error: "--m3-error",
    onError: "--m3-on-error",
    errorContainer: "--m3-error-container",
    onErrorContainer: "--m3-on-error-container",
    primaryFixed: "--m3-primary-fixed",
    primaryFixedDim: "--m3-primary-fixed-dim",
    onPrimaryFixed: "--m3-on-primary-fixed",
    onPrimaryFixedVariant: "--m3-on-primary-fixed-variant",
    secondaryFixed: "--m3-secondary-fixed",
    secondaryFixedDim: "--m3-secondary-fixed-dim",
    onSecondaryFixed: "--m3-on-secondary-fixed",
    onSecondaryFixedVariant: "--m3-on-secondary-fixed-variant",
    tertiaryFixed: "--m3-tertiary-fixed",
    tertiaryFixedDim: "--m3-tertiary-fixed-dim",
    onTertiaryFixed: "--m3-on-tertiary-fixed",
    onTertiaryFixedVariant: "--m3-on-tertiary-fixed-variant"
  };

  function applyScheme() {
    var scheme = H.colorScheme;
    var root = document.documentElement.style;
    if (!scheme) {
      /* No host scheme (browser testing / shim-only): restore the fallback
       * severity tints built from the Okabe-Ito hues in diag.css. */
      root.setProperty("--ok-line", "rgba(0, 158, 115, .5)");
      root.setProperty("--ok-bg", "rgba(0, 158, 115, .12)");
      root.setProperty("--warn-line", "rgba(230, 159, 0, .5)");
      root.setProperty("--warn-bg", "rgba(230, 159, 0, .12)");
      root.setProperty("--bad-line", "rgba(213, 94, 0, .55)");
      root.setProperty("--bad-bg", "rgba(213, 94, 0, .13)");
      document.body.classList.remove("scheme-light");
      return;
    }
    var kebab = function (name) {
      return "--m3-" + name.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
    };
    var n, v;
    for (n in scheme) {
      if (typeof scheme[n] !== "string" || n === "darkThemeEnabled") { continue; }
      if (!/^#[0-9A-Fa-f]{3,8}$/.test(scheme[n])) { continue; }
      v = M3_CSS_BY_HUDIY[n] || kebab(n);
      root.setProperty(v, scheme[n]);
    }
    /* Severity role bindings and their translucent carrier tints:
     * ok -> tertiary, warn -> tertiaryContainer (M3 has no warn slot; warn
     * rides the dynamic tertiaryContainer), bad -> error, info/blue -> primary. */
    function hexToRgba(hex, alpha) {
      var h = hex.replace("#", "");
      if (h.length === 3) { h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]; }
      if (h.length === 8) { h = h.slice(0, 6); }
      var r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16),
          b = parseInt(h.slice(4, 6), 16);
      if (isNaN(r) || isNaN(g) || isNaN(b)) { return null; }
      return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
    }
    var okT = scheme.tertiary, warnT = scheme.tertiaryContainer ||
      scheme.primaryContainer || scheme.secondaryContainer,
      badT = scheme.error || scheme.errorContainer,
      infoT = scheme.primary || scheme.secondary;
    var pairs = [
      [okT, "--ok-line", "--ok-bg", .5, .12],
      [warnT, "--warn-line", "--warn-bg", .5, .12],
      [badT, "--bad-line", "--bad-bg", .55, .13],
      [infoT, "--info-line", "--info-bg" , .5, .12]
    ];
    var i, base, c;
    for (i = 0; i < pairs.length; i++) {
      base = pairs[i][0];
      if (typeof base !== "string" || !/^#[0-9A-Fa-f]{3,8}$/.test(base)) { continue; }
      c = hexToRgba(base, pairs[i][3]);
      if (c) { root.setProperty(pairs[i][1], c); }
      c = hexToRgba(base, pairs[i][4]);
      if (c) { root.setProperty(pairs[i][2], c); }
    }
    document.documentElement.classList.toggle("scheme-light", !scheme.darkThemeEnabled);
    document.body.classList.toggle("scheme-light", !scheme.darkThemeEnabled);
  }

  /* ------------------------------------------------------- input: keyboard */

  var KEYMAP = {
    ArrowDown: function () { kbOn(); return moveFocus(1); },
    ArrowUp: function () { kbOn(); return moveFocus(-1); },
    ArrowRight: function () { kbOn(); return horizontal(1); },
    ArrowLeft: function () { kbOn(); return horizontal(-1); },
    Enter: function () { kbOn(); activate(); return true; },
    ' ': function () { kbOn(); activate(); return true; },
    Escape: function () { return back(); },
    Backspace: function () { return back(); }
  };

  function kbOn() {
    if (effectiveBridge() === 'dom' && !S.kb) { S.kb = true; syncKeyMode(); }
  }

  /* Direct nav hook for the wheel/key shim (tools/keyboard_shim.py): Hudiy's
   * native input stack never routes physical keys to third-party overlay
   * webviews on this build (proven by CDP trials, 11 Sep), so the shim reads
   * the wheel at /dev/input and calls this instead.
   *
   * SELF-CONTAINED on purpose: it does NOT call the closure's moveFocus/
   * paintFocus/S.focus chain (that chain was seen returning false with visible
   * .ctl buttons present - the shim needs a nav path that cannot be wedged by
   * page state). It walks the ACTIVE screen's visible .ctl nodes directly and
   * paints the .focused ring itself, mirroring the same visual states.
   */
  window.__diagKeyNav = function (step) {
    var root = document.querySelector('.screen.active') ||
               document.querySelector('[data-screen="' + document.body.getAttribute('data-screen') + '"]');
    if (!root) { return false; }
    var nodes = root.querySelectorAll('.ctl');
    /* .ctl buttons also live in the GLOBAL #actions bar (renderActions), not
     * inside the .screen sections - without it the Start screen has zero
     * controls and nav silently no-ops (found 11 Sep). Merge, order kept. */
    var bar = document.getElementById('actions');
    var barCtl = bar ? Array.prototype.slice.call(bar.querySelectorAll('.ctl')) : [];
    var all = Array.prototype.slice.call(nodes).concat(barCtl);
    /* Top-bar Back button must be reachable by the wheel too (user, 11 Sep). */
    var backBtn = document.getElementById('back');
    if (backBtn && !backBtn.hidden) { all.push(backBtn); }
    var list = [];
    for (var i = 0; i < all.length; i++) {
      var n = all[i];
      if (n.disabled) { continue; }
      if (n.offsetParent === null && n.tagName !== 'A') { continue; }
      list.push(n);
    }
    if (!list.length) { return false; }
    var cur = 0;
    for (var j = 0; j < list.length; j++) {
      if (list[j].classList.contains('focused')) { cur = j; break; }
    }
    if (step === 'activate') {
      var target = list[cur];
      if (target) { target.click(); }
      return true;
    }
    if (step === 'back') {
      var backBtn = document.querySelector('#back');
      if (backBtn && !backBtn.hidden) { backBtn.click(); return true; }
      return false;
    }
    /* wrap around so the wheel cycles the ring instead of stopping at ends */
    var next = cur;
    if (step === 'prev') { next = (cur === 0 ? list.length - 1 : cur - 1); }
    else { next = (cur === list.length - 1 ? 0 : cur + 1); }
    for (var k = 0; k < list.length; k++) { list[k].classList.remove('focused'); }
    list[next].classList.add('focused');
    document.body.classList.add('kb');
    if (list[next].scrollIntoView) { list[next].scrollIntoView({ block: 'nearest' }); }
    return true;
  };

  function onKey(event) {
    if (effectiveBridge() === 'bridge' && S.attached) { return; }
    // The OK/Enter alias listener (wire()) runs first and consumes Enter/OK by
    // clicking the focused control; without this guard the same keypress also
    // reaches KEYMAP and activates a second time - on S0 that clicked
    // "Start health scan" and then "Cancel" on the freshly-shown S1 (found
    // live in the browser test, 14 Sep).
    if (event.defaultPrevented) { return; }
    if (event.altKey || event.ctrlKey || event.metaKey) { return; }
    var fn = KEYMAP[event.key];
    if (!fn) { return; }
    var handled = fn();
    if (handled) { event.preventDefault(); }
  }

  /* Mouse wheel / trackpad: the desktop counterpart of scroll left/right
   * (keys `1`/`2` in Hudiy's scheme). Walks the same focus ring as the
   * keyboard and the knob; a region that can genuinely scroll (the report
   * <pre>) keeps its native scrolling. Deltas accumulate so a trackpad's
   * fine-grained stream still moves one step per gesture notch. Handled in
   * every mode - Hudiy does not translate wheel input, so this is ours. */
  var wheelAcc = 0, wheelAt = 0;
  function onWheel(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) { return; }
    var delta = event.deltaY * (event.deltaMode === 1 ? 16 : 1);
    if (!delta) { return; }
    var el = event.target;
    while (el && el !== document.body) {
      var style = window.getComputedStyle(el);
      if ((style.overflowY === 'auto' || style.overflowY === 'scroll') &&
          el.scrollHeight > el.clientHeight + 2) {
        return;                          /* let the region scroll natively */
      }
      el = el.parentElement;
    }
    var now = Date.now();
    if (now - wheelAt > 350) { wheelAcc = 0; }      /* new gesture */
    wheelAt = now;
    wheelAcc += delta;
    if (Math.abs(wheelAcc) < 40) { event.preventDefault(); return; }
    var step = wheelAcc > 0 ? 1 : -1;
    wheelAcc = 0;
    kbOn();
    if (moveFocus(step)) { event.preventDefault(); }
  }

  /* -------------------------------------------------------- input: touch */

  var touch = null;

  function onTouchStart(event) {
    var t = event.changedTouches[0];
    touch = { x: t.clientX, y: t.clientY, at: Date.now(), moved: false };
  }

  function onTouchEnd(event) {
    if (!touch) { return; }
    var t = event.changedTouches[0];
    var dx = t.clientX - touch.x;
    var dy = t.clientY - touch.y;
    var wasTap = Math.abs(dx) < 12 && Math.abs(dy) < 12 && (Date.now() - touch.at) < 700;
    touch = null;
    if (effectiveBridge() === 'dom' && S.kb) { S.kb = false; syncKeyMode(); }
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.4) {
      if (dx > 0) { back(); }
      else if (S.screen === 'S3' || S.screen === 'S8') { horizontal(1); }
      return;
    }
    if (wasTap) {
      // A tap is a touch action: move the ring to whatever was tapped, then let
      // the element's own click handler fire.
      var node = event.target && event.target.closest ? event.target.closest('.ctl') : null;
      if (node) {
        var list = controls();
        var idx = list.indexOf(node);
        if (idx >= 0) { S.focus = idx; paintFocus(); }
      }
    }
  }

  /* ----------------------------------------------------------------- data */

  function fetchJSON(url) {
    return fetch(url, { cache: 'no-store', headers: { 'Accept': 'application/json' } })
      .then(function (res) {
        return res.text().then(function (body) {
          var data = null;
          try { data = JSON.parse(body); } catch (err) { data = null; }
          return { ok: res.ok, status: res.status, data: data, raw: body, error: res.ok ? null : ('HTTP ' + res.status) };
        });
      })
      .catch(function (err) {
        return { ok: false, status: 0, data: null, raw: '', error: (err && err.name === 'AbortError') ? 'cancelled' : 'network error' };
      });
  }

  function pollAllowed() {
    /* Poll while the page is visible. The bridge's `activated` flag stays
     * false on this Hudiy build even while the overlay is shown (same
     * input-routing quirk as the wheel - see docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md),
     * so it must NOT gate polling: gating on it froze the link chip at
     * "unknown" while the user was looking at the page. */
    if (document.visibilityState === 'hidden') { return false; }
    return true;
  }

  function pollHealth() {
    if (!pollAllowed()) { return; }
    fetchJSON('/health').then(function (res) {
      if (res.ok && res.data) { S.health = res.data; S.healthErr = null; }
      else { S.healthErr = res.error; }
      renderHeader();
      if (S.screen === 'S0') { renderHome(); }
    });
  }

  function startPolling() {
    if (S.linkTimer) { return; }
    pollHealth();
    S.linkTimer = window.setInterval(pollHealth, S.busy ? SCAN_LINK_MS : HEALTH_MS);
  }

  function stopPolling() {
    if (S.linkTimer) { window.clearInterval(S.linkTimer); S.linkTimer = null; }
  }

  function restartPolling() {
    stopPolling();
    if (pollAllowed()) { startPolling(); }
  }

  /* One in-flight scan at a time (the ELM link is single-flight). A deep
   * scan rides the same S1 screen but its result lands in S.deep, never in
   * S.scan - a focused re-read must not wipe the health summary. */
  function launchScan(kind) {
    if (S.busy) { return; }
    S.busy = true;
    S.scanKind = kind;
    if (kind !== 'deep') { S.degraded = null; }
    S.started = Date.now();
    S.elapsed = 0;
    S.scanAbort = (typeof AbortController === 'function') ? new AbortController() : null;
    go('S1');
    render();
    restartPolling();
    if (S.tickTimer) { window.clearInterval(S.tickTimer); }
    S.tickTimer = window.setInterval(function () {
      S.elapsed = (Date.now() - S.started) / 1000;
      if (S.screen === 'S1') { $('scanTimer').textContent = num(S.elapsed, 1) + 's'; }
    }, 200);

    var url, sections;
    if (kind === 'deep') {
      url = '/scan?sections=' + DEEP.join(',');
      sections = DEEP.slice();
    } else {
      url = '/scan' + (S.scope === 'quick' ? ('?sections=' + QUICK.join(',')) : '');
      sections = (S.scope === 'quick') ? QUICK.slice() : null;
    }
    S.scanSections = sections;
    var opts = { cache: 'no-store', headers: { 'Accept': 'application/json' } };
    if (S.scanAbort) { opts.signal = S.scanAbort.signal; }

    fetch(url, opts)
      .then(function (res) {
        return res.text().then(function (body) {
          var data = null;
          try { data = JSON.parse(body); } catch (err) { data = null; }
          return { ok: res.ok, status: res.status, data: data, raw: body };
        });
      })
      .then(function (res) {
        finishScan(null, res);
      })
      .catch(function (err) {
        finishScan((err && err.name === 'AbortError') ? 'cancelled' : 'request failed', null);
      });
  }

  function startScan() {
    launchScan(S.scope === 'quick' ? 'quick' : 'full');
  }

  function startDeepScan() {
    launchScan('deep');
  }

  function finishScan(error, res) {
    var kind = S.scanKind || 'full';
    S.busy = false;
    S.scanKind = null;
    S.scanSections = null;
    if (S.tickTimer) { window.clearInterval(S.tickTimer); S.tickTimer = null; }
    S.scanAbort = null;
    restartPolling();

    if (error === 'cancelled') {
      toast('Cancelled on this screen. The diagnostics lane was mid-query, so the ECU read ' +
            'finishes on the backend and is not cached here.', 'warn');
      go(S.scan ? 'S2' : 'S0');
      return;
    }
    if (error || !res || !res.data) {
      if (kind === 'deep') {
        toast('Deep scan failed: the diagnostics lane did not answer (' + (error || 'no payload') +
              '). The last report is untouched.', 'bad');
        var back = S.scan ? 'S2' : 'S0';
        go(back);
        shakeOnce($(back === 'S2' ? 'verdict' : 's0Hero'));   // motion: error shake
        return;
      }
      S.degraded = { status: 'error', reason: 'the diagnostics lane did not answer (' + (error || 'no payload') + ')' };
      toast('Scan failed: ' + S.degraded.reason, 'bad');
      go('S0');
      shakeOnce($('s0Hero'));   // motion: error shake (snackbar kept)
      return;
    }
    var data = res.data;
    if (data.report) {
      if (kind === 'deep') {
        var rows = (data.report.allpids || []);
        S.deep = { rows: rows, support: data.report.support || null,
                   at: new Date(), duration_s: data.duration_s, sections: data.sections };
        if (!rows.length) {
          toast('Deep scan came back with no PID rows - discovery found no support map. The last report is untouched.', 'warn');
          go(S.scan ? 'S2' : 'S0');
          return;
        }
        var heard = rows.filter(function (r) { return r.ok; }).length;
        toast('Deep read finished in ' + num(data.duration_s, 1) + ' s: ' +
              heard + ' of ' + rows.length + ' PIDs answered.', 'info');
        markScanDone();   // motion: spinner pops to check before leaving S1
        go('S9');
        return;
      }
      S.scan = data;
      S.scanAt = new Date();
      S.degraded = null;
      S.dtcTab = 'stored';
      S.dtcIndex = 0;
      S.vin = null;
      S.vinState = 'idle';
      S.vinOnline = null;
      S.reportBody = null;
      S.reportState = 'idle';
      if (kind === 'full') { S.deep = null; }  // the full report carries a fresher allpids read
      toast('Scan finished in ' + num(data.duration_s, 1) + ' s: ' + (data.summary || 'complete') + '.', 'info');
      markScanDone();   // motion: spinner pops to check before leaving S1
      go('S2');
      return;
    }
    if (kind === 'deep') {
      toast('Deep scan produced no data: ' +
            ((res.data && (res.data.reason || res.data.status)) || 'the ECU did not answer') +
            '. The last report is untouched.', 'warn');
      go(S.scan ? 'S2' : 'S0');
      return;
    }
    S.degraded = {
      status: data.status || 'unavailable',
      reason: data.reason || 'the ECU did not answer, so no report was produced'
    };
    toast('No scan data: ' + S.degraded.reason, 'warn');
    go('S0');
    shakeOnce($('s0Hero'));   // motion: failure panel shakes once (snackbar kept)
  }

  function cancelScan() {
    if (!S.busy) { return; }
    if (S.scanAbort) { S.scanAbort.abort(); }
    else { finishScan('cancelled', null); }
  }

  /* --------------------------------------------------------------- toast */

  var toastTimer = null;

  function toast(text, sev) {
    var box = $('toast');
    box.textContent = text;
    box.setAttribute('data-sev', sev || 'info');
    box.hidden = false;
    if (toastTimer) { window.clearTimeout(toastTimer); }
    toastTimer = window.setTimeout(function () { box.hidden = true; }, TOAST_MS);
  }

  /* -------------------------------------------------------------- motion */

  /* Motion pass (2026-09-24): class toggles only — no per-frame JS timers,
   * no layout-property animation. Animations live in diag.css; these helpers
   * just attach/remove classes on state changes. Knob/shim navigation and
   * the window.__diagKeyNav() contract are untouched. */

  function ensureScanMark() {
    var top = document.querySelector('.card-scan .scan-top');
    if (!top) { return null; }
    var mark = top.querySelector('.scan-mark');
    if (!mark) {
      mark = el('span', 'scan-mark');
      mark.setAttribute('aria-hidden', 'true');
      top.insertBefore(mark, top.firstChild);
    }
    return mark;
  }

  // Cross-fade a label to new text: sets the text once, re-triggers the
  // opacity-only .swap-in keyframe via a reflow (no timers).
  function swapText(node, text) {
    if (!node || node.__swapText === text) { return; }
    node.__swapText = text;
    node.textContent = text;
    node.classList.remove('swap-in');
    void node.offsetWidth;
    node.classList.add('swap-in');
  }

  // One-shot cross-fade for fresh content: animates once per key, never on
  // every render.
  function revealOnce(node, key) {
    if (!node || node.__revealKey === key) { return; }
    node.__revealKey = key;
    node.classList.remove('reveal-in');
    void node.offsetWidth;
    node.classList.add('reveal-in');
  }

  // One-shot error shake: the class runs the keyframe once, animationend
  // removes it so the panel settles with no residual transform.
  function shakeOnce(node) {
    if (!node) { return; }
    node.classList.remove('shake-once');
    void node.offsetWidth;
    var done = function () {
      node.classList.remove('shake-once');
      node.removeEventListener('animationend', done);
    };
    node.addEventListener('animationend', done);
    node.classList.add('shake-once');
  }

  // S1 status states: shimmer + spinner while busy, static otherwise.
  function syncScanMotion() {
    var label = document.querySelector('.card-scan .scan-label');
    var mark = ensureScanMark();
    var busy = !!S.busy;
    if (label) {
      label.classList.toggle('is-scanning', busy);
      if (busy) {
        swapText(label, S.scanKind === 'deep' ? 'Reading every PID' : 'Asking the ECU');
      } else {
        label.classList.remove('swap-in');
      }
    }
    if (mark) {
      if (busy) { mark.classList.remove('is-done'); mark.classList.add('is-busy'); }
      else { mark.classList.remove('is-busy'); }
    }
  }

  // Scan completed: spinner pops into a drawn check (scale/rotate/opacity).
  function markScanDone() {
    var label = document.querySelector('.card-scan .scan-label');
    var mark = document.querySelector('.card-scan .scan-mark');
    if (mark) { mark.classList.remove('is-busy'); mark.classList.add('is-done'); }
    if (label) { label.classList.remove('is-scanning'); swapText(label, 'Scan complete'); }
  }

  /* ----------------------------------------------------------------- boot */

  function wire() {
    $('back').addEventListener('click', function () { back(); });
    // "OK"/Enter alias: some keyboards and remotes send Enter for select rather
    // than space. Only fires when nothing else in this page consumed the key.
    document.addEventListener('keydown', function (event) {
      if (effectiveBridge() === 'bridge' && S.attached) { return; }
      if (event.key !== 'Enter' && event.key !== 'OK') { return; }
      if (event.defaultPrevented) { return; }
      var list = controls();
      if (!list.length) { return; }
      if (S.focus < 0 || S.focus >= list.length) { S.focus = 0; }
      if (!S.kb) { S.kb = true; syncKeyMode(); }
      paintFocus();
      list[S.focus].click();
      event.preventDefault();
    });

    document.addEventListener('keydown', onKey);
    document.addEventListener('wheel', onWheel, { passive: false });
    var app = $('app');
    app.addEventListener('touchstart', onTouchStart, { passive: true });
    app.addEventListener('touchend', onTouchEnd, { passive: true });
    document.addEventListener('visibilitychange', function () { restartPolling(); });
    window.addEventListener('beforeunload', stopPolling);
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      document.body.classList.add('reduced-motion');
    }
  }

  function start() {
    boot();
    /* Hudiy keeps one webview alive per overlay URL: a relaunch from the menu
     * re-SHOWS the same page, so a previous session's exitOverlay() state
     * (body.exited + hidden #app) would survive and paint a blank screen
     * (found live 11 Sep). Present = undo our own teardown, every show. */
    document.body.classList.remove('exited');
    leaving = false;
    var unhide = $('app');
    if (unhide) { unhide.hidden = false; }
    wire();
    applyScheme();
    /* Hudiy injects colorScheme AFTER page load and does not fire
     * onColorSchemeChanged for the initial value, so re-apply briefly until
     * the bridge hands it over (self-cancels once tokens stop changing). */
    var schemeSettle = 0;
    var schemeTimer = setInterval(function () {
      schemeSettle += 1;
      applyScheme();
      if (schemeSettle >= 10 || (window.hudiy && window.hudiy.colorScheme)) { clearInterval(schemeTimer); }
    }, 500);
    renderHeader();
    go('S0');
    syncKeyMode();
    startPolling();
    // Identity decode is free and offline: fetch it as soon as we have a VIN.
    window.setTimeout(function () { if (S.screen === 'S7') { loadVin(); } }, 0);
    window.__DIAG = S;   // bench hook: lets a trial read/modify state during bring-up
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}());
