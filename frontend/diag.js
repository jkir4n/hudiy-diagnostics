/* Hudiy Diagnostics - overlay page logic (V1_SPEC screens S0-S8).
 *
 * Design notes
 * ------------
 * Input parity (V1_SPEC rule 6): every action on every screen is reachable by
 * touch, by the Hudiy key/knob bridge, and by a gesture. The bridge is primary:
 * window.hudiy carries inputFocus/activated plus the callback set documented in
 * docs/HUDIY_KEYBOARD_CONTROL_SCHEME.md (onMoveToNextControl /
 * onMoveToPreviousControl return true when the page consumed the key, false to
 * hand it back to Hudiy). A DOM keydown fallback drives exactly the same state
 * machine for browser testing and for installs where the bridge is absent.
 * localStorage ("diag.bridge") / "?bridge=" / the settings screen pick the path
 * (auto-detect by default: bridge once Hudiy attaches, DOM until then).
 *
 * The page never talks to the OBD adapter. It reads the backend HTTP lane only
 * (same origin, so no CORS dance): /health, /scan, /report, /dtc, /vin.
 * Everything the UI shows comes from those responses - no vehicle knowledge is
 * baked in here.
 */

(function () {
  'use strict';

  var HEALTH_MS = 5000;      // slow poll: link state + replay badge
  var SCAN_LINK_MS = 1200;   // faster only while a scan is in flight
  var SECTIONS = ['discovery', 'dtc', 'pending', 'readiness', 'mode06', 'identity', 'live'];
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
      'Clearing codes is not part of this version: the backend has no Mode 04 call at all. If ' +
      'codes ever need clearing, the cost is that every readiness monitor restarts from zero.'
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
    stale_handle: 'ECU reconnecting',
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
    S8: { title: 'Report', subtitle: 'Settings' }
  };

  var PARENT = { S1: 'S0', S2: 'S0', S3: 'S2', S4: 'S3', S5: 'S2', S6: 'S2', S7: 'S2', S8: 'S0' };

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
    var note = S.scope === 'quick'
      ? 'Quick scan: fault codes, pending codes and the readiness wall only.'
      : 'A full scan reads the supported-PID map, stored / pending / permanent codes, the ' +
        'readiness wall, Mode 06 monitor tests and vehicle identity - usually under 30 seconds.';
    if (S.degraded) { note = 'Last attempt: ' + (S.degraded.reason || S.degraded.status) + '.'; }
    $('scanNote').textContent = note;
    var sec = (S.scan && S.scan.sections) ? S.scan.sections : null;
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

      (rec.tests || []).forEach(function (t) {
        var li = el('li');
        var row = el('div', 'row flat');
        var main = el('div', 'row-main');
        add(main, el('div', 'row-text', t.tid_name || ('TID 0x' + (t.tid || 0).toString(16))));
        var sub = (t.uas_name || '') + ' \u00b7 limits ' + num(t.min && t.min.scaled, 0) + '..' +
          num(t.max && t.max.scaled, 0) + (t.raw_hex && S.raw ? ' \u00b7 raw ' + t.raw_hex : '');
        add(main, el('div', 'row-sub', sub));
        var value = el('div', 'row-value');
        add(value, document.createTextNode(num(t.value && t.value.scaled, 0)));
        if (t.value && t.value.unit) { add(value, el('span', 'row-unit', t.value.unit)); }
        add(row, main, value);
        if (t.within_limits === true) { add(row, chip('ok', '\u2713', 'Within limits')); }
        else if (t.within_limits === false) { add(row, chip('bad', '!', 'Outside limits')); }
        else { add(row, chip('warn', '!', 'Unclear')); }
        add(li, row);
        list.appendChild(li);
      });

      if (rec.parse_note || rec.layout_ambiguous) {
        var note = el('li');
        add(note, el('p', 'stamp', rec.parse_note || 'The record layout was ambiguous, so values ' +
          'may be misread \u2014 shown as reported, not as a judgement.'));
        list.appendChild(note);
      }
    });
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
    if (S.reportState === 'loading') { pre.textContent = 'Fetching the ' + S.reportFmt + ' report\u2026'; }
    else if (S.reportState === 'error') { pre.textContent = 'Report unavailable.\n\n' + (S.reportBody || 'The backend did not answer /report.'); }
    else if (S.reportBody) { pre.textContent = S.reportBody; }
    else { pre.textContent = COPY.noReport; }

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
    } else if (S.screen === 'S1') {
      // Cancel must be live exactly while a scan is in flight - it is the only
      // way out of S1 (the footer button is the sole cancel affordance).
      plan.push(button('Cancel', '', cancelScan, !!S.busy));
      plan.push(el('span', 'grow'));
      if (!S.busy && S.degraded) { plan.push(button('Retry', 'btn-primary', startScan)); }
    } else if (S.screen === 'S2') {
      plan.push(button('Scan again', 'btn-primary', startScan));
      plan.push(button('Fault codes', '', function () { go('S3'); }, done));
      plan.push(button('Report', '', function () { go('S8'); loadReport(); }));
    } else if (S.screen === 'S3') {
      plan.push(button('Health summary', '', function () { go('S2'); }));
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
      plan.push(button('Health summary', 'btn-primary', function () { go('S2'); }));
      var a = el('a', 'btn', 'Download ' + S.reportFmt.toUpperCase());
      a.href = '/report?format=' + encodeURIComponent(S.reportFmt);
      a.setAttribute('download', downloadName());
      a.style.textDecoration = 'none';
      a.style.display = 'inline-flex';
      a.style.alignItems = 'center';
      plan.push(a);
    }

    plan.forEach(function (n) { bar.appendChild(n); });
    return bar;
  }

  /* ---------------------------------------------------------------- focus */

  function controls() {
    var root = screenEl();
    if (!root) { return []; }
    var nodes = root.querySelectorAll('.ctl');
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
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
    if (S.screen === 'S0') { return false; }
    var target = PARENT[S.screen] || 'S0';
    return go(target);
  }

  /* ------------------------------------------------------- input: bridge */

  window.hudiy = window.hudiy || {};
  var H = window.hudiy;

  H.onAttached = function () {
    S.attached = true;
    document.body.setAttribute('data-bridge', effectiveBridge());
    syncKeyMode();
    startPolling();
  };

  H.onInputFocusChanged = function () { syncKeyMode(); };
  H.onActivatedChanged = function () {
    syncKeyMode();
    if (H.activated) { startPolling(); } else { stopPolling(); }
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

  function applyScheme() {
    var scheme = H.colorScheme;
    if (!scheme) { return; }
    var root = document.documentElement.style;
    if (scheme.outline) { root.setProperty('--focus', scheme.outline); }
    if (scheme.surfaceContainer) { root.setProperty('--panel', scheme.surfaceContainer); }
    if (scheme.onSurface) { root.setProperty('--ink', scheme.onSurface); }
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

  function onKey(event) {
    if (effectiveBridge() === 'bridge' && S.attached) { return; }
    if (event.altKey || event.ctrlKey || event.metaKey) { return; }
    var fn = KEYMAP[event.key];
    if (!fn) { return; }
    var handled = fn();
    if (handled) { event.preventDefault(); }
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
    if (document.visibilityState === 'hidden') { return false; }
    if (effectiveBridge() === 'bridge' && S.attached && H.activated === false) { return false; }
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

  function startScan() {
    if (S.busy) { return; }
    S.busy = true;
    S.degraded = null;
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

    var url = '/scan' + (S.scope === 'quick' ? ('?sections=' + QUICK.join(',')) : '');
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

  function finishScan(error, res) {
    S.busy = false;
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
      S.degraded = { status: 'error', reason: 'the diagnostics lane did not answer (' + (error || 'no payload') + ')' };
      toast('Scan failed: ' + S.degraded.reason, 'bad');
      go('S0');
      return;
    }
    var data = res.data;
    if (data.report) {
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
      toast('Scan finished in ' + num(data.duration_s, 1) + ' s: ' + (data.summary || 'complete') + '.', 'info');
      go('S2');
      return;
    }
    S.degraded = {
      status: data.status || 'unavailable',
      reason: data.reason || 'the ECU did not answer, so no report was produced'
    };
    toast('No scan data: ' + S.degraded.reason, 'warn');
    go('S0');
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
    wire();
    applyScheme();
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
