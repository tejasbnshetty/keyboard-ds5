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
  status: {}, held: null, capture: null, retry: 500,
};
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
      break;
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
    ? `${s.setup_error || "Not set up."} Run the setup steps in the README (discover, login, pair), then restart the app.`
    : "";

  const busy = $("#busy");
  const msg = s.busy || (s.free_in > 0 ? `PS5 is still closing the last session - you can connect in ${s.free_in} s` : "");
  busy.hidden = !msg;
  busy.textContent = msg;

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
  if (!$("#modal").hidden || typingInField(e)) return;
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

connect();
