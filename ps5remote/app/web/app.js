// SPDX-License-Identifier: AGPL-3.0-only
// PS5 Remote interface. Talks to the local server over one WebSocket (see server.py).
// Untrusted text is only ever inserted with textContent, never innerHTML.
"use strict";

const BUTTON_LABELS = {
  up: "Up", down: "Down", left: "Left", right: "Right", cross: "Cross ✕", circle: "Circle ○",
  triangle: "Triangle △", square: "Square □", options: "Options", ps: "PS", l1: "L1", r1: "R1",
  l2: "L2", r2: "R2",
};
const POWER_LABELS = {
  on: "On", asleep: "Asleep", unreachable: "Not reachable", unknown: "Checking…",
  setup_needed: "Setup needed",
};

const state = {
  ws: null, settings: null, keymaps: null, buttons: [], repeatable: new Set(),
  status: {}, held: null, capture: null, retry: 500, setup: null,
};
const wiz = { step: 1, lastAction: null, migrationAsked: false, wasActive: false };
const token = new URLSearchParams(location.search).get("token") || "";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ---- connection --------------------------------------------------------------------------

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws?token=${encodeURIComponent(token)}`);
  state.ws = ws;
  ws.onopen = () => { state.retry = 500; send({ type: "hello" }); };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    setPower("unknown");
    setTimeout(connect, state.retry);
    state.retry = Math.min(state.retry * 2, 5000);
  };
}

function send(msg) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(msg));
}

function handle(msg) {
  switch (msg.type) {
    case "init":
      state.buttons = msg.buttons;
      state.repeatable = new Set(msg.repeatable);
      applySettings(msg.settings);
      applyKeymaps(msg.keymaps);
      $("#personal-badge").hidden = !(msg.build && msg.build.personal);
      break;
    case "setup": applySetup(msg); break;
    case "status": applyStatus(msg); break;
    case "settings": applySettings(msg.settings); break;
    case "keymaps": applyKeymaps(msg.keymaps); break;
    case "event": log(msg.message, msg.kind, msg.time); break;
    case "error": log(msg.message, "error"); break;
  }
}

// ---- status ------------------------------------------------------------------------------

function setPower(power) {
  const pill = $("#power");
  pill.textContent = POWER_LABELS[power] || power;
  pill.className = `pill ${power}`;
}

function applyStatus(s) {
  state.status = s;
  setPower(s.power);
  $("#app-name").textContent = s.app || "";
  $("#link-dot").classList.toggle("on", !!s.connected);
  $("#link-text").textContent = s.connected ? "Connected" : "Not connected";

  $("#streaming-warning").hidden = !s.streaming_app;
  $("#streaming-name").textContent = s.streaming_app || "";

  const setup = $("#setup-warning");
  setup.hidden = s.power !== "setup_needed";
  setup.textContent = s.power === "setup_needed"
    ? `${s.setup_error || "Not set up."} Open Settings → Run setup again.`
    : "";

  const busy = $("#busy");
  const msg = s.busy || (s.free_in > 0 ? `PS5 is still closing the last session - you can connect in ${s.free_in} s` : "");
  busy.hidden = !msg;
  busy.textContent = msg;

  const wizPower = $("#wiz-power");
  wizPower.textContent = POWER_LABELS[s.power] || s.power;
  wizPower.className = `pill ${s.power}`;
  $("#wiz-test-rest").disabled = s.power !== "on" || !!s.busy;
  $("#wiz-test-wake").disabled = s.power !== "asleep" || !!s.busy;

  $("#wake").disabled = s.power !== "asleep" || !!s.busy;
  $("#rest").disabled = s.power !== "on" || !!s.busy;
  $("#disconnect").disabled = !s.connected;
}

function log(text, kind = "info", time = "") {
  const li = document.createElement("li");
  li.className = kind;
  li.textContent = `${time || new Date().toLocaleTimeString()}  ${text}`;
  const list = $("#log");
  list.prepend(li);
  while (list.children.length > 6) list.lastChild.remove();
}

// ---- buttons (on-screen and keyboard) ----------------------------------------------------

function buttonDown(button) {
  document.querySelectorAll(`[data-button="${button}"]`).forEach((el) => el.classList.add("pressed"));
  if (state.repeatable.has(button)) {
    if (state.held && state.held !== button) buttonUp(state.held);
    state.held = button;
    send({ type: "hold", button });
  } else {
    send({ type: "press", button });
  }
}

function buttonUp(button) {
  document.querySelectorAll(`[data-button="${button}"]`).forEach((el) => el.classList.remove("pressed"));
  if (state.held === button) {
    state.held = null;
    send({ type: "release", button });
  }
}

function releaseAll() {
  if (state.held) buttonUp(state.held);
  $$(".btn.pressed").forEach((el) => el.classList.remove("pressed"));
}

$$(".btn[data-button]").forEach((el) => {
  const button = el.dataset.button;
  el.addEventListener("pointerdown", (e) => { e.preventDefault(); el.setPointerCapture(e.pointerId); buttonDown(button); });
  const up = () => buttonUp(button);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
  el.addEventListener("lostpointercapture", up);
});

function activeProfile() {
  return state.keymaps ? state.keymaps.profiles[state.keymaps.active] : {};
}

function buttonForKey(code) {
  const profile = activeProfile();
  return Object.keys(profile).find((b) => profile[b] === code);
}

function typingInField(e) {
  const t = e.target;
  return t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA");
}

document.addEventListener("keydown", (e) => {
  if (state.capture) { e.preventDefault(); finishCapture(e.code); return; }
  if (!$("#modal").hidden || typingInField(e) || wizardActive()) return;
  if (state.settings && e.code === state.settings.profile_hotkey) {
    e.preventDefault();
    if (!e.repeat) cycleProfile();
    return;
  }
  const button = buttonForKey(e.code);
  if (!button) return;
  e.preventDefault();
  if (!e.repeat) buttonDown(button);   // the server does hold-to-repeat, not the OS
});

document.addEventListener("keyup", (e) => {
  const button = buttonForKey(e.code);
  if (button) { e.preventDefault(); buttonUp(button); }
});

window.addEventListener("blur", releaseAll);  // never leave a button held if focus moves away

// ---- actions -----------------------------------------------------------------------------

$("#wake").addEventListener("click", () => send({ type: "wake" }));
$("#disconnect").addEventListener("click", () => send({ type: "disconnect" }));
$("#rest").addEventListener("click", async () => {
  if (await confirmBox("Put the PS5 into rest mode?")) send({ type: "rest" });
});

$$(".tab").forEach((tab) => tab.addEventListener("click", () => {
  $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab.dataset.tab}`));
  tab.blur();
}));

// ---- modal helpers -----------------------------------------------------------------------

function confirmBox(text, withInput = false, initial = "") {
  return new Promise((resolve) => {
    const modal = $("#modal");
    const input = $("#modal-input");
    $("#modal-text").textContent = text;
    input.hidden = !withInput;
    input.value = initial;
    modal.hidden = false;
    (withInput ? input : $("#modal-ok")).focus();
    const done = (ok) => {
      modal.hidden = true;
      $("#modal-ok").onclick = $("#modal-cancel").onclick = input.onkeydown = null;
      resolve(withInput ? (ok ? input.value.trim() : null) : ok);
    };
    $("#modal-ok").onclick = () => done(true);
    $("#modal-cancel").onclick = () => done(false);
    input.onkeydown = (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); };
  });
}

// ---- key maps ----------------------------------------------------------------------------

function keyLabel(code) {
  if (!code) return "—";
  const arrows = { ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→" };
  if (arrows[code]) return arrows[code];
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit\d$/.test(code)) return code.slice(5);
  return code;
}

function applyKeymaps(km) {
  state.keymaps = km;
  const select = $("#profile-select");
  select.replaceChildren(...Object.keys(km.profiles).map((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    opt.selected = name === km.active;
    return opt;
  }));
  $("#profile-delete").disabled = Object.keys(km.profiles).length < 2;
  renderKeyTable();
}

function renderKeyTable() {
  const profile = activeProfile();
  const counts = {};
  Object.values(profile).forEach((k) => { if (k) counts[k] = (counts[k] || 0) + 1; });
  const rows = state.buttons.map((button) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "key-row" + (counts[profile[button]] > 1 ? " conflict" : "");
    const name = document.createElement("span");
    name.textContent = BUTTON_LABELS[button] || button;
    const key = document.createElement("span");
    key.className = "key" + (profile[button] ? "" : " unbound");
    key.textContent = keyLabel(profile[button]);
    row.append(name, key);
    row.addEventListener("click", () => startCapture({ kind: "bind", button }));
    return row;
  });
  $("#key-table").replaceChildren(...rows);
  const clashes = Object.keys(counts).filter((k) => counts[k] > 1);
  const box = $("#key-conflicts");
  box.hidden = clashes.length === 0;
  box.textContent = clashes.length ? `Conflicts: ${clashes.map(keyLabel).join(", ")} bound more than once.` : "";
}

function saveKeymaps() { send({ type: "save_keymaps", keymaps: state.keymaps }); }

function startCapture(capture) {
  state.capture = capture;
  $("#capture-text").textContent = capture.kind === "bind"
    ? `Press a key for ${BUTTON_LABELS[capture.button]}…` : "Press a key for the profile hotkey…";
  $("#capture").hidden = false;
}

async function finishCapture(code) {
  const capture = state.capture;
  state.capture = null;
  $("#capture").hidden = true;
  if (code === "Escape") return;  // Esc always cancels
  if (capture.kind === "hotkey") {
    if (allBoundKeys().has(code)) { log(`${keyLabel(code)} is used in a key map; pick another hotkey.`, "error"); return; }
    $("#hotkey-capture").dataset.code = code;
    $("#hotkey-capture").textContent = keyLabel(code);
    return;
  }
  if (state.settings && code === state.settings.profile_hotkey) {
    log(`${keyLabel(code)} is the profile hotkey and can't be bound.`, "error");
    return;
  }
  const profile = activeProfile();
  const other = Object.keys(profile).find((b) => b !== capture.button && profile[b] === code);
  if (other) {
    const move = await confirmBox(
      `${keyLabel(code)} is already bound to ${BUTTON_LABELS[other]}. Move it to ${BUTTON_LABELS[capture.button]}? (${BUTTON_LABELS[other]} will be unbound.)`);
    if (!move) return;
    profile[other] = "";
  }
  profile[capture.button] = code;
  renderKeyTable();
  saveKeymaps();
}

function allBoundKeys() {
  return new Set(Object.values(state.keymaps.profiles).flatMap((p) => Object.values(p)).filter(Boolean));
}

function cycleProfile() {
  const names = Object.keys(state.keymaps.profiles);
  const next = names[(names.indexOf(state.keymaps.active) + 1) % names.length];
  setProfile(next);
  log(`Profile: ${next}`);
}

function setProfile(name) {
  releaseAll();
  state.keymaps.active = name;
  applyKeymaps(state.keymaps);
  saveKeymaps();
}

$("#profile-select").addEventListener("change", (e) => { setProfile(e.target.value); e.target.blur(); });

$("#profile-add").addEventListener("click", async () => {
  const name = await confirmBox("Name for the new profile (copies the current one):", true, "");
  if (!name) return;
  if (state.keymaps.profiles[name]) { log(`A profile called ${name} already exists.`, "error"); return; }
  state.keymaps.profiles[name] = { ...activeProfile() };
  setProfile(name);
});

$("#profile-delete").addEventListener("click", async () => {
  const name = state.keymaps.active;
  if (!(await confirmBox(`Delete the profile "${name}"?`))) return;
  delete state.keymaps.profiles[name];
  setProfile(Object.keys(state.keymaps.profiles)[0]);
});

$("#keys-reset").addEventListener("click", async () => {
  if (await confirmBox("Reset all key maps and profiles to the defaults?")) send({ type: "reset_keymaps" });
});

// ---- settings ----------------------------------------------------------------------------

function applySettings(s) {
  state.settings = s;
  const form = $("#settings-form");
  for (const [name, value] of Object.entries(s)) {
    const field = form.elements[name];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = value; else field.value = value;
  }
  const hk = $("#hotkey-capture");
  hk.dataset.code = s.profile_hotkey;
  hk.textContent = keyLabel(s.profile_hotkey);
  $("#hotkey-hint").textContent = `${keyLabel(s.profile_hotkey)} switches keyboard profile.`;
}

$("#hotkey-capture").addEventListener("click", () => startCapture({ kind: "hotkey" }));

$("#settings-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target.elements;
  send({
    type: "save_settings",
    settings: {
      press_ms: Number(f.press_ms.value),
      idle_timeout_min: Number(f.idle_timeout_min.value),
      repeat_delay_ms: Number(f.repeat_delay_ms.value),
      repeat_interval_ms: Number(f.repeat_interval_ms.value),
      safe_connect: f.safe_connect.checked,
      profile_hotkey: $("#hotkey-capture").dataset.code,
    },
  });
});

// ---- setup wizard ------------------------------------------------------------------------

function wizardActive() { return !!(state.setup && state.setup.active); }

function wizSteps() {
  // Re-pairing skips the rest-mode tips (already done once).
  return state.setup && state.setup.mode === "repair" ? [1, 2, 3, 5] : [1, 2, 3, 4, 5];
}

function wizSend(msg) {
  wiz.lastAction = msg;
  send(msg);
}

async function applySetup(s) {
  state.setup = s;
  document.body.classList.toggle("wizard-on", s.active);
  $("#wizard").hidden = !s.active;
  if (s.active && !wiz.wasActive) {   // wizard just opened: start at step 1 and search
    wiz.step = 1;
    wiz.lastAction = null;
    releaseAll();
    if (!s.consoles.length && !s.console && !s.busy) wizSend({ type: "setup_discover" });
  }
  wiz.wasActive = s.active;

  // Settings > PS5 & account
  $("#account-info").textContent = s.existing_account
    ? `Signed in as ${s.existing_account}${s.current_ps5 ? ` · paired with the PS5 at ${s.current_ps5}` : ""}.`
    : "Not signed in.";
  $("#data-dir").textContent = `Data folder: ${s.data_dir}`;
  $("#wiz-data-dir").textContent = `Data folder: ${s.data_dir}`;
  $("#forget").disabled = !s.existing_account && !s.current_ps5;

  // Offer to copy an older data folder (first run of the .exe).
  if (s.migration && !wiz.migrationAsked) {
    wiz.migrationAsked = true;
    const yes = await confirmBox(
      `Found existing pairing data in ${s.migration}. Copy it into ${s.data_dir}? (The original stays where it is.) Choose Cancel to set up fresh.`);
    send({ type: "migrate", accept: yes });
  }
  renderWizard();
}

function renderWizard() {
  const s = state.setup;
  if (!s || !s.active) return;
  const steps = wizSteps();
  if (!steps.includes(wiz.step)) wiz.step = steps.find((n) => n > wiz.step) || 5;

  $$("#wiz-progress li").forEach((li) => {
    const n = Number(li.dataset.step);
    li.classList.toggle("skipped", !steps.includes(n));
    li.classList.toggle("current", n === wiz.step);
    li.classList.toggle("done", n < wiz.step);
  });
  $$(".wiz-step").forEach((el) => el.classList.toggle("active", Number(el.dataset.step) === wiz.step));

  const busy = $("#wiz-busy");
  busy.hidden = !s.busy && !s.login_window_open;
  busy.textContent = s.busy || (s.login_window_open ? "Finish signing in in the PlayStation window…" : "");
  const err = $("#wiz-error");
  err.hidden = !s.error;
  err.textContent = s.error || "";
  $("#wiz-retry").hidden = !s.error || !wiz.lastAction;
  $("#wiz-cancel").hidden = !s.can_cancel;

  // Step 1
  $("#wiz-consoles").replaceChildren(...s.consoles.map((c) => {
    const b = document.createElement("button");
    b.className = "action choice" + (s.console && s.console.ip === c.ip ? " selected" : "");
    b.textContent = `${c.name} — ${c.ip} (${c.state})`;
    b.addEventListener("click", () => wizSend({ type: "setup_use_console", ip: c.ip }));
    return b;
  }));
  const chosen = $("#wiz-chosen");
  chosen.hidden = !s.console;
  chosen.textContent = s.console ? `Using ${s.console.name} at ${s.console.ip} ✓` : "";

  // Step 2
  $("#wiz-psn-missing").hidden = s.psn_configured;
  $("#wiz-signin").disabled = !s.psn_configured || !!s.busy || s.login_window_open;
  $("#wiz-keep").hidden = !s.existing_account || !!s.signed_in;
  $("#wiz-existing").textContent = s.existing_account || "";
  $("#wiz-signin-hint").textContent = s.embedded_login
    ? "A PlayStation sign-in window opens. It closes by itself once you're signed in."
    : "Your browser opens Sony's sign-in page. Afterwards, paste the address below.";
  if (s.paste_needed) $("#wiz-paste").hidden = false;
  const signed = $("#wiz-signed");
  signed.hidden = !s.signed_in;
  signed.textContent = s.signed_in ? `Signed in as ${s.signed_in} ✓` : "";

  // Step 3
  $("#wiz-paired").hidden = !s.paired;
  $("#wiz-pair").disabled = !!s.busy;

  // Navigation
  const idx = steps.indexOf(wiz.step);
  $("#wiz-back").disabled = idx <= 0 || !!s.busy;
  const ready = { 1: !!s.console, 2: !!s.signed_in, 3: !!s.paired, 4: true, 5: false }[wiz.step];
  $("#wiz-next").hidden = wiz.step === 5;
  $("#wiz-next").disabled = !ready || !!s.busy;
}

function wizGo(delta) {
  const steps = wizSteps();
  const idx = Math.max(0, Math.min(steps.length - 1, steps.indexOf(wiz.step) + delta));
  wiz.step = steps[idx];
  wiz.lastAction = null;
  renderWizard();
}

$("#wiz-next").addEventListener("click", () => wizGo(1));
$("#wiz-back").addEventListener("click", () => wizGo(-1));
$("#wiz-retry").addEventListener("click", () => { if (wiz.lastAction) send(wiz.lastAction); });
$("#wiz-cancel").addEventListener("click", () => send({ type: "setup_cancel" }));
$("#wiz-search").addEventListener("click", () => wizSend({ type: "setup_discover" }));
$("#wiz-use-ip").addEventListener("click", () => wizSend({ type: "setup_use_console", ip: $("#wiz-ip").value.trim() }));
$("#wiz-ip").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#wiz-use-ip").click(); });
$("#wiz-signin").addEventListener("click", () => wizSend({ type: "setup_psn_open" }));
$("#wiz-keep-btn").addEventListener("click", () => wizSend({ type: "setup_psn_keep" }));
$("#wiz-show-paste").addEventListener("click", () => { $("#wiz-paste").hidden = false; $("#wiz-paste-url").focus(); });
$("#wiz-paste-btn").addEventListener("click", () => {
  const url = $("#wiz-paste-url").value.trim();
  $("#wiz-paste-url").value = "";   // don't keep the one-time code on screen
  if (url) wizSend({ type: "setup_psn_paste", url });
});
$("#wiz-pin").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#wiz-pair").click(); });
$("#wiz-pair").addEventListener("click", () => {
  const pin = $("#wiz-pin").value.replace(/\D/g, "");
  if (pin.length !== 8) { log("The PIN must be 8 digits.", "error"); return; }
  $("#wiz-pin").value = "";
  wizSend({ type: "setup_pair", pin });
});
$("#wiz-test-rest").addEventListener("click", () => send({ type: "rest" }));
$("#wiz-test-wake").addEventListener("click", () => send({ type: "wake" }));
$("#wiz-test-press").addEventListener("click", () => send({ type: "press", button: "ps" }));
$("#wiz-finish").addEventListener("click", () => send({ type: "setup_finish" }));

// Settings > PS5 & account
$("#repair").addEventListener("click", () => send({ type: "setup_start", mode: "repair" }));
$("#rerun-setup").addEventListener("click", () => send({ type: "setup_start", mode: "full" }));
$("#forget").addEventListener("click", async () => {
  if (await confirmBox("Sign out and delete the PS5 pairing, your PSN account ID and the PS5 address from this PC? Settings and key maps are kept. You'll need to set up again (including a new PIN from the PS5).")) {
    send({ type: "forget_all" });
  }
});

connect();
