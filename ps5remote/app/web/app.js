// SPDX-License-Identifier: AGPL-3.0-only
// Untrusted text is only ever inserted with textContent, never innerHTML.
"use strict";

const BUTTON_LABELS = {
  up: "Up", down: "Down", left: "Left", right: "Right", cross: "Cross ✕", circle: "Circle ○",
  triangle: "Triangle △", square: "Square □", options: "Options", ps: "PS", l1: "L1", r1: "R1",
  l2: "L2", r2: "R2", l3: "L3 (left stick click)", r3: "R3 (right stick click)", touchpad: "Touchpad",
};
const ACTION_LABELS = {
  ...BUTTON_LABELS,
  ls_up: "Up", ls_down: "Down", ls_left: "Left", ls_right: "Right",
  rs_up: "Up", rs_down: "Down", rs_left: "Left", rs_right: "Right",
  walk: "Walk (half tilt)", light_trigger: "Light L2/R2",
};
const ACTION_GROUPS = [
  ["Left stick", ["ls_up", "ls_down", "ls_left", "ls_right", "walk"]],
  ["Buttons", ["cross", "circle", "square", "triangle", "l1", "r1", "l2", "r2", "light_trigger",
    "l3", "r3", "options", "touchpad", "ps"]],
  ["D-pad", ["up", "down", "left", "right"]],
  ["Right stick from keys (the mouse also moves it while captured)", ["rs_up", "rs_down", "rs_left", "rs_right"]],
];
const INPUT_LABELS = {
  Mouse0: "Left click", Mouse1: "Middle click", Mouse2: "Right click", Mouse3: "Back button",
  Mouse4: "Forward button", WheelUp: "Wheel up", WheelDown: "Wheel down",
  ShiftLeft: "L-Shift", ShiftRight: "R-Shift", AltLeft: "L-Alt", AltRight: "R-Alt",
  ControlLeft: "L-Ctrl", ControlRight: "R-Ctrl", Space: "Space",
  ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→",
};
// Compact names for the keycaps on the on-screen buttons.
const SHORT_LABELS = {
  Mouse0: "LMB", Mouse1: "MMB", Mouse2: "RMB", Mouse3: "M4", Mouse4: "M5",
  WheelUp: "Wheel↑", WheelDown: "Wheel↓", ShiftLeft: "LShift", ShiftRight: "RShift",
  AltLeft: "LAlt", AltRight: "RAlt", ControlLeft: "LCtrl", ControlRight: "RCtrl",
  Backspace: "Bksp", Escape: "Esc", Backslash: "\\", Slash: "/", Comma: ",", Period: ".",
  Semicolon: ";", Quote: "'", BracketLeft: "[", BracketRight: "]", Minus: "-", Equal: "=",
  Backquote: "`", CapsLock: "Caps",
};
const POWER_LABELS = {
  on: "On", asleep: "Asleep", unreachable: "Not reachable", unknown: "Checking…",
  setup_needed: "Setup needed",
};
const MOUSE_SEND_MS = 8;        // mouse movement batches, ~125 a second
const WHEEL_GAP_MS = 60;        // one wheel "press" per notch, not per scroll event
const MAX_MOUSE_EVENT = 2000;   // drop the occasional bogus jump right after capture

const state = {
  ws: null, settings: null, keymaps: null, buttons: [], buttonSet: new Set(), actions: [],
  repeatable: new Set(), status: {}, held: null, capture: null, retry: 500, setup: null,
  captured: false, mouse: { dx: 0, dy: 0, timer: null }, wheelAt: 0,
};
const heldInputs = new Map();   // input -> { action, kind: "menu" | "act" }
const wiz = { step: 1, lastAction: null, migrationAsked: false, wasActive: false };
const token = new URLSearchParams(location.search).get("token") || "";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws?token=${encodeURIComponent(token)}`);
  state.ws = ws;
  ws.onopen = () => { state.retry = 500; send({ type: "hello" }); };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    setPower("unknown");
    releaseCapture();
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
      state.buttonSet = new Set(msg.buttons);
      state.actions = msg.actions;
      state.templates = msg.templates || {};
      state.repeatable = new Set(msg.repeatable);
      applySettings(msg.settings);
      applyKeymaps(msg.keymaps);
      $("#personal-badge").hidden = !(msg.build && msg.build.personal);
      applyAbout(msg.build || {});
      break;
    case "setup": applySetup(msg); break;
    case "status": applyStatus(msg); break;
    case "settings": applySettings(msg.settings); break;
    case "keymaps": applyKeymaps(msg.keymaps); break;
    case "pad": renderPad(msg); break;
    case "game_reset":
      releaseCapture();
      releaseAllInputs();
      log("Released everything: the PS5 session ended. Press a key or capture the mouse to reconnect.", "dropped");
      break;
    case "event": log(msg.message, msg.kind, msg.time); break;
    case "error": log(msg.message, "error"); break;
  }
}

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

// On-screen buttons and menu-style profiles: taps, and held directions repeat ------------

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

// Bound inputs (keys, mouse buttons) -> actions ---------------------------------------

function activeProfile() {
  return state.keymaps ? state.keymaps.profiles[state.keymaps.active] : null;
}

function actionFor(input) {
  const p = activeProfile();
  return p ? p.bindings[input] : undefined;
}

/** Returns true if the input is bound (so the browser's default should be blocked). */
function inputDown(input) {
  const action = actionFor(input);
  if (!action) return false;
  if (heldInputs.has(input)) return true;
  if (state.buttonSet.has(action) && !activeProfile().hold_buttons) {
    heldInputs.set(input, { action, kind: "menu" });
    buttonDown(action);
  } else {
    heldInputs.set(input, { action, kind: "act" });
    $$(`[data-button="${action}"]`).forEach((el) => el.classList.add("pressed"));
    send({ type: "act", action, down: true });
  }
  return true;
}

function inputUp(input) {
  const held = heldInputs.get(input);
  if (!held) return false;
  heldInputs.delete(input);   // released by what it pressed, even if the profile changed since
  if (held.kind === "menu") {
    buttonUp(held.action);
  } else {
    send({ type: "act", action: held.action, down: false });
    if (![...heldInputs.values()].some((h) => h.action === held.action)) {
      $$(`[data-button="${held.action}"]`).forEach((el) => el.classList.remove("pressed"));
    }
  }
  return true;
}

function releaseAllInputs() {
  [...heldInputs.keys()].forEach(inputUp);
  releaseAll();
  send({ type: "neutral" });
}

function typingInField(e) {
  const t = e.target;
  return t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA");
}

function inputsBlocked() {
  return !$("#modal").hidden || !$("#about").hidden || wizardActive();
}

// About dialog ---------------------------------------------------------------------------

function applyAbout(build) {
  $("#about-version").textContent = build.version || "";
  $("#about-personal").hidden = !build.personal;
  const link = (id, url) => {
    const a = $(id);
    if (typeof url === "string" && url.startsWith("https://")) a.href = url; else a.removeAttribute("href");
  };
  link("#about-source", build.source_url);
  link("#about-license", build.license_url);
  link("#about-provenance", build.provenance_url);
}

function openAbout() {
  if (state.captured) releaseCapture();
  if (heldInputs.size || state.held) releaseAllInputs();
  $("#about").hidden = false;
  $("#about-close").focus();
}

function closeAbout() { $("#about").hidden = true; }

$("#about-open").addEventListener("click", (e) => { e.currentTarget.blur(); openAbout(); });
$("#about-open-settings").addEventListener("click", (e) => { e.currentTarget.blur(); openAbout(); });
$("#about-close").addEventListener("click", closeAbout);
$("#about").addEventListener("click", (e) => { if (e.target.id === "about") closeAbout(); });
$("#about").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeAbout(); } });

document.addEventListener("keydown", (e) => {
  if (state.capture) { e.preventDefault(); finishCapture(e.code); return; }
  if (inputsBlocked() || typingInField(e)) return;
  if (state.settings && e.code === state.settings.mouse_toggle_key) {
    e.preventDefault();
    if (!e.repeat) toggleMouseCapture();
    return;
  }
  if (state.settings && e.code === state.settings.profile_hotkey) {
    e.preventDefault();
    if (!e.repeat) cycleProfile();
    return;
  }
  if (e.repeat) {   // the server repeats held directions; the OS repeat is ignored
    if (actionFor(e.code)) e.preventDefault();
    return;
  }
  if (inputDown(e.code)) e.preventDefault();
});

document.addEventListener("keyup", (e) => {
  if (inputUp(e.code) || actionFor(e.code)) e.preventDefault();   // e.g. Alt: no menu
});

// Never leave anything held if focus moves away or the window is minimised.
function letGo() {
  releaseCapture();
  if (heldInputs.size || state.held) releaseAllInputs();
}
window.addEventListener("blur", letGo);
document.addEventListener("visibilitychange", () => { if (document.hidden) letGo(); });

// Mouse capture (pointer lock) --------------------------------------------------------

async function requestCapture() {
  const target = document.body;
  try {
    const result = target.requestPointerLock({ unadjustedMovement: true });  // raw, no OS acceleration
    if (result && result.then) await result;
  } catch (err) {
    try {
      const result = target.requestPointerLock();
      if (result && result.then) await result;
    } catch (err2) {
      log(`Couldn't capture the mouse (${err2.name || err2}). Click "Capture mouse" to try again.`, "error");
    }
  }
}

function releaseCapture() {
  if (document.pointerLockElement) document.exitPointerLock();
}

// The captured mouse moves the right stick in every profile; the profile stays as it is.
function toggleMouseCapture() {
  if (state.captured) releaseCapture(); else requestCapture();
}

/** True if the profile binds keys to the left stick (e.g. WASD). */
function movesLeftStick(p) {
  return !!p && Object.values(p.bindings).some((action) => action.startsWith("ls_"));
}

$("#capture-mouse").addEventListener("click", (e) => { e.currentTarget.blur(); toggleMouseCapture(); });

document.addEventListener("pointerlockchange", () => {
  const on = document.pointerLockElement === document.body;
  if (on === state.captured) return;
  state.captured = on;
  send({ type: "capture", on });
  if (on) {
    state.mouse.timer = setInterval(flushMouse, MOUSE_SEND_MS);
  } else {
    clearInterval(state.mouse.timer);
    state.mouse.dx = state.mouse.dy = 0;
    if (heldInputs.size || state.held) releaseAllInputs();   // centred and released
  }
  renderCaptureState();
});

document.addEventListener("pointerlockerror", () => {
  log("The window refused to capture the mouse. Click inside it first, or wait a second after pressing Esc.", "error");
});

function renderCaptureState() {
  $("#captured-banner").hidden = !state.captured;
  const btn = $("#capture-mouse");
  btn.classList.toggle("on", state.captured);
  const key = state.settings ? keyLabel(state.settings.mouse_toggle_key) : "F1";
  btn.textContent = state.captured ? `Release mouse (${key} / Esc)` : `Capture mouse (${key})`;
  $("#captured-key").textContent = key;
}

document.addEventListener("mousemove", (e) => {
  if (!state.captured) return;
  if (Math.abs(e.movementX) > MAX_MOUSE_EVENT || Math.abs(e.movementY) > MAX_MOUSE_EVENT) return;
  state.mouse.dx += e.movementX;
  state.mouse.dy += e.movementY;
});

function flushMouse() {
  const m = state.mouse;
  if (!m.dx && !m.dy) return;
  send({ type: "mouse", dx: m.dx, dy: m.dy });
  m.dx = m.dy = 0;
}

// Mouse buttons: only while captured (otherwise they click the interface). The back and
// forward buttons are always blocked so they can't navigate away from the app.
document.addEventListener("mousedown", (e) => {
  if (state.capture) return;   // binding: handled by the capture overlay
  if (e.button >= 3) e.preventDefault();
  if (!state.captured || inputsBlocked()) return;
  e.preventDefault();
  inputDown(`Mouse${e.button}`);
});
document.addEventListener("mouseup", (e) => {
  if (e.button >= 3) e.preventDefault();
  if (inputUp(`Mouse${e.button}`)) e.preventDefault();
});
document.addEventListener("auxclick", (e) => { if (e.button >= 3 || state.captured) e.preventDefault(); });
document.addEventListener("contextmenu", (e) => { if (state.captured || state.capture) e.preventDefault(); });

document.addEventListener("wheel", (e) => {
  if (!state.captured || inputsBlocked() || !e.deltaY) return;
  e.preventDefault();
  const now = performance.now();
  if (now - state.wheelAt < WHEEL_GAP_MS) return;
  state.wheelAt = now;
  const action = actionFor(e.deltaY < 0 ? "WheelUp" : "WheelDown");
  if (action && state.buttonSet.has(action)) {
    send({ type: "press", button: action });
    flashButton(action);
  }
}, { passive: false });

// Stick visualiser --------------------------------------------------------------------

function placeDot(el, numEl, [x, y]) {
  el.style.left = `${50 + x * 42}%`;
  el.style.top = `${50 + y * 42}%`;
  numEl.textContent = `${x.toFixed(2)}, ${(-y).toFixed(2)}`;   // shown with up = positive
}

function renderPad(p) {
  placeDot($("#viz-left"), $("#viz-left-num"), p.left);
  placeDot($("#viz-right"), $("#viz-right-num"), p.right);
  $("#viz-l2").style.height = `${((p.buttons.l2 || 0) / 255) * 100}%`;
  $("#viz-r2").style.height = `${((p.buttons.r2 || 0) / 255) * 100}%`;
  const held = Object.keys(p.buttons).map((b) => (b === "l2" || b === "r2") && p.buttons[b] < 255
    ? `${b.toUpperCase()} ${Math.round((p.buttons[b] / 255) * 100)}%` : (BUTTON_LABELS[b] || b));
  $("#viz-buttons").textContent = held.length ? `Held: ${held.join(", ")}` : "No buttons held";
}

function shortLabel(code) { return SHORT_LABELS[code] || keyLabel(code); }

function inputsFor(action) {
  const p = activeProfile();
  return p ? Object.keys(p.bindings).filter((input) => p.bindings[input] === action) : [];
}

/** Shows each on-screen button's keys/mouse inputs in the current profile, and the sticks'. */
function renderKeycaps() {
  $$(".btn[data-button]").forEach((el) => {
    let cap = el.querySelector(".keycap");
    if (!cap) {
      cap = document.createElement("span");
      cap.className = "keycap";
      cap.setAttribute("aria-hidden", "true");
      el.append(cap);
    }
    const inputs = inputsFor(el.dataset.button);
    cap.textContent = inputs.slice(0, 2).map(shortLabel).join(" · ") + (inputs.length > 2 ? " …" : "");
    cap.hidden = !inputs.length;
    el.title = inputs.length ? `${BUTTON_LABELS[el.dataset.button]}: ${inputs.map(keyLabel).join(", ")}` : "";
  });
  const dirs = (prefix) => ["up", "left", "down", "right"]
    .map((d) => inputsFor(`${prefix}_${d}`)[0]).filter(Boolean).map(shortLabel);
  const walk = inputsFor("walk")[0];
  const left = dirs("ls");
  $("#viz-left-keys").textContent = [left.join(" "), walk ? `${shortLabel(walk)} walk` : ""]
    .filter(Boolean).join(" · ");
  $("#viz-right-keys").textContent = ["Mouse", dirs("rs").join(" ")].filter(Boolean).join(" · ");
}

function flashButton(button) {
  const els = $$(`[data-button="${button}"]`);
  els.forEach((el) => el.classList.add("pressed"));
  setTimeout(() => els.forEach((el) => {
    if (![...heldInputs.values()].some((h) => h.action === button)) el.classList.remove("pressed");
  }), 120);
}

function renderGamingHint() {
  const p = activeProfile();
  const hint = $("#gaming-hint");
  if (!p) { hint.textContent = ""; return; }
  const key = state.settings ? keyLabel(state.settings.mouse_toggle_key) : "F1";
  const name = state.keymaps.active;
  const gaming = state.keymaps.profiles.Gaming && name !== "Gaming" ? ' Switch to "Gaming" for WASD movement.' : "";
  hint.textContent = movesLeftStick(p)
    ? `${key} captures the mouse to aim. Release it before using the rest of this window.`
    : `${key} captures the mouse to aim. Profile "${name}" doesn't bind keys to the left stick.${gaming}`;
  renderCaptureState();
}

// Profiles and the Keys tab -----------------------------------------------------------

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

function keyLabel(code) {
  if (!code) return "—";
  if (INPUT_LABELS[code]) return INPUT_LABELS[code];
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
  const p = activeProfile();
  $("#opt-hold").checked = !!p.hold_buttons;
  renderKeyTable();
  renderGamingHint();
  renderKeycaps();
}

function renderKeyTable() {
  const bindings = activeProfile().bindings;
  const byAction = {};
  Object.entries(bindings).forEach(([input, action]) => (byAction[action] = byAction[action] || []).push(input));
  const groups = ACTION_GROUPS.map(([title, actions]) => {
    const group = document.createElement("div");
    group.className = "bind-group";
    const h = document.createElement("h4");
    h.textContent = title;
    const grid = document.createElement("div");
    grid.className = "bind-grid";
    actions.filter((a) => state.actions.includes(a)).forEach((action) => {
      const row = document.createElement("div");
      row.className = "bind-row";
      const name = document.createElement("span");
      name.textContent = ACTION_LABELS[action] || action;
      const keys = document.createElement("span");
      keys.className = "bind-keys";
      (byAction[action] || []).forEach((input) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.title = "Click to remove";
        chip.textContent = keyLabel(input);
        chip.addEventListener("click", () => { delete bindings[input]; renderKeyTable(); saveKeymaps(); });
        keys.append(chip);
      });
      const add = document.createElement("button");
      add.type = "button";
      add.className = "chip add";
      add.textContent = "+";
      add.title = `Add a key or mouse input for ${ACTION_LABELS[action] || action}`;
      add.addEventListener("click", () => startCapture({ kind: "bind", action }));
      keys.append(add);
      row.append(name, keys);
      grid.append(row);
    });
    group.append(h, grid);
    return group;
  });
  $("#key-table").replaceChildren(...groups);
}

function saveKeymaps() { send({ type: "save_keymaps", keymaps: state.keymaps }); }

function startCapture(capture) {
  state.capture = capture;
  const bind = capture.kind === "bind";
  $("#capture-text").textContent = bind
    ? `Press a key, click a mouse button or turn the wheel for ${ACTION_LABELS[capture.action]}…`
    : "Press a key for this hotkey…";
  $("#capture-sub").textContent = "Esc to cancel";
  $("#capture").hidden = false;
}

// While binding, the overlay takes mouse buttons and the wheel too.
$("#capture").addEventListener("mousedown", (e) => {
  if (!state.capture || state.capture.kind !== "bind") return;
  e.preventDefault();
  finishCapture(`Mouse${e.button}`);
});
$("#capture").addEventListener("wheel", (e) => {
  if (!state.capture || state.capture.kind !== "bind" || !e.deltaY) return;
  e.preventDefault();
  finishCapture(e.deltaY < 0 ? "WheelUp" : "WheelDown");
}, { passive: false });

async function finishCapture(code) {
  const capture = state.capture;
  state.capture = null;
  $("#capture").hidden = true;
  if (code === "Escape") return;
  if (capture.kind === "hotkey") {
    if (/^(Mouse|Wheel)/.test(code)) return;
    if (allBoundKeys().has(code)) { log(`${keyLabel(code)} is used in a key map; pick another key.`, "error"); return; }
    const other = $$("[data-setting]");
    for (const el of other) {
      if (el !== capture.el && el.dataset.code === code) { log(`${keyLabel(code)} is already the other hotkey.`, "error"); return; }
    }
    capture.el.dataset.code = code;
    capture.el.textContent = keyLabel(code);
    return;
  }
  const hotkeys = state.settings ? [state.settings.profile_hotkey, state.settings.mouse_toggle_key] : [];
  if (hotkeys.includes(code)) {
    log(`${keyLabel(code)} is a hotkey (Settings tab) and can't be bound.`, "error");
    return;
  }
  if (code.startsWith("Wheel") && !state.buttonSet.has(capture.action)) {
    log("The mouse wheel can only press buttons.", "error");
    return;
  }
  const bindings = activeProfile().bindings;
  const other = bindings[code];
  if (other === capture.action) return;
  if (other) {
    const move = await confirmBox(
      `${keyLabel(code)} already does ${ACTION_LABELS[other]}. Move it to ${ACTION_LABELS[capture.action]}?`);
    if (!move) return;
  }
  bindings[code] = capture.action;
  renderKeyTable();
  saveKeymaps();
}

function allBoundKeys() {
  return new Set(Object.values(state.keymaps.profiles).flatMap((p) => Object.keys(p.bindings)));
}

function cycleProfile() {
  const names = Object.keys(state.keymaps.profiles);
  const next = names[(names.indexOf(state.keymaps.active) + 1) % names.length];
  setProfile(next);
  log(`Profile: ${next}`);
}

function setProfile(name) {
  if (heldInputs.size || state.held) releaseAllInputs();
  state.keymaps.active = name;
  applyKeymaps(state.keymaps);
  saveKeymaps();
}

$("#profile-select").addEventListener("change", (e) => { setProfile(e.target.value); e.target.blur(); });

$("#opt-hold").addEventListener("change", (e) => {
  if (heldInputs.size || state.held) releaseAllInputs();
  activeProfile().hold_buttons = e.target.checked;
  saveKeymaps();
  e.target.blur();
});

const MAX_PROFILES = 12;
const PROFILE_NAME = /^[\p{L}\p{N}_ .\-+&()]{1,24}$/u;   // as keymaps.py allows

function profileNameError(name, renaming = null) {
  if (!PROFILE_NAME.test(name)) return "Profile names can have up to 24 letters, numbers, spaces and . - + & ( ) _";
  if (name !== renaming && state.keymaps.profiles[name]) return `A profile called "${name}" already exists.`;
  return "";
}

/** Asks for a profile name, and optionally a choice from a list. Resolves {name, choice} or null. */
function profileDialog(text, initial, choices = null) {
  return new Promise((resolve) => {
    const modal = $("#modal");
    const input = $("#modal-input");
    const select = $("#modal-select");
    const error = $("#modal-error");
    $("#modal-text").textContent = text;
    input.hidden = false;
    input.value = initial;
    select.hidden = !choices;
    select.replaceChildren(...(choices || []).map(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      return opt;
    }));
    error.hidden = true;
    modal.hidden = false;
    input.focus();
    input.select();
    const done = (ok) => {
      const name = input.value.trim();
      if (ok) {
        const problem = profileNameError(name, initial || null);
        if (problem) { error.textContent = problem; error.hidden = false; input.focus(); return; }
      }
      modal.hidden = select.hidden = error.hidden = true;
      $("#modal-ok").onclick = $("#modal-cancel").onclick = input.onkeydown = null;
      resolve(ok ? { name, choice: select.value } : null);
    };
    $("#modal-ok").onclick = () => done(true);
    $("#modal-cancel").onclick = () => done(false);
    input.onkeydown = (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); };
  });
}

function copyProfile(p) { return { ...p, bindings: { ...p.bindings } }; }

$("#profile-add").addEventListener("click", async () => {
  if (Object.keys(state.keymaps.profiles).length >= MAX_PROFILES) {
    log(`You can have up to ${MAX_PROFILES} profiles. Delete one first.`, "error");
    return;
  }
  const choices = [
    ["copy", `A copy of "${state.keymaps.active}"`],
    ...Object.keys(state.templates).map((name) => [`template:${name}`, `The default ${name} layout`]),
    ["empty-game", "Nothing bound: gaming style (buttons held down)"],
    ["empty-menu", "Nothing bound: menu style (taps, directions repeat)"],
  ];
  const result = await profileDialog("New profile. Name it, and choose what it starts with:", "", choices);
  if (!result) return;
  let profile;
  if (result.choice === "copy") profile = copyProfile(activeProfile());
  else if (result.choice.startsWith("template:")) profile = copyProfile(state.templates[result.choice.slice(9)]);
  else {
    profile = { hold_buttons: result.choice === "empty-game", bindings: {} };
  }
  state.keymaps.profiles[result.name] = profile;
  setProfile(result.name);
  log(`Created the profile "${result.name}". Bind its keys below.`);
});

$("#profile-rename").addEventListener("click", async () => {
  const old = state.keymaps.active;
  const result = await profileDialog(`Rename the profile "${old}" to:`, old);
  if (!result || result.name === old) return;
  const profiles = {};   // keep the order, swap the name
  Object.entries(state.keymaps.profiles).forEach(([name, p]) => { profiles[name === old ? result.name : name] = p; });
  state.keymaps.profiles = profiles;
  state.keymaps.active = result.name;
  applyKeymaps(state.keymaps);
  saveKeymaps();
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

// Settings ----------------------------------------------------------------------------

function applySettings(s) {
  state.settings = s;
  const form = $("#settings-form");
  for (const [name, value] of Object.entries(s)) {
    const field = form.elements[name];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = value; else field.value = value;
  }
  $$("[data-setting]").forEach((el) => {
    el.dataset.code = s[el.dataset.setting];
    el.textContent = keyLabel(s[el.dataset.setting]);
  });
  $("#hotkey-hint").textContent = `${keyLabel(s.profile_hotkey)} switches keyboard profile.`;
  renderCaptureState();
}

$$("[data-setting]").forEach((el) => el.addEventListener("click", () => startCapture({ kind: "hotkey", el })));

$("#settings-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const settings = {};
  for (const field of e.target.elements) {
    if (!field.name) continue;
    if (field.type === "checkbox") settings[field.name] = field.checked;
    else if (field.type === "number") settings[field.name] = Number(field.value);
    else settings[field.name] = field.value;
  }
  $$("[data-setting]").forEach((el) => { settings[el.dataset.setting] = el.dataset.code; });
  send({ type: "save_settings", settings });
});

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
  if (s.active && !wiz.wasActive) {
    wiz.step = 1;
    wiz.lastAction = null;
    releaseAll();
    if (!s.consoles.length && !s.console && !s.busy) wizSend({ type: "setup_discover" });
  }
  wiz.wasActive = s.active;

  $("#account-info").textContent = s.existing_account
    ? `Signed in as ${s.existing_account}${s.current_ps5 ? ` · paired with the PS5 at ${s.current_ps5}` : ""}.`
    : "Not signed in.";
  $("#data-dir").textContent = `Data folder: ${s.data_dir}`;
  $("#wiz-data-dir").textContent = `Data folder: ${s.data_dir}`;
  $("#forget").disabled = !s.existing_account && !s.current_ps5;

  // First run of the .exe: offer to copy an older data folder.
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

  // Without sign-in values, entering the account ID is the only path: show it, hide sign-in.
  $("#wiz-psn-missing").hidden = s.psn_configured;
  $("#wiz-signin-block").hidden = !s.psn_configured;
  if (!s.psn_configured) $("#wiz-paste").hidden = true;
  $("#wiz-show-manual").hidden = !s.psn_configured;
  if (!s.psn_configured) $("#wiz-manual").hidden = false;
  $("#wiz-manual-btn").disabled = !!s.busy;
  $("#wiz-signin").disabled = !s.psn_configured || !!s.busy || s.login_window_open;
  $("#wiz-keep").hidden = !s.existing_account || !!s.signed_in;
  $("#wiz-existing").textContent = s.existing_account || "";
  $("#wiz-signin-hint").textContent = s.embedded_login
    ? "A PlayStation sign-in window opens. It closes by itself once you're signed in."
    : "Your browser opens Sony's sign-in page. Afterwards, paste the address below.";
  if (s.paste_needed) $("#wiz-paste").hidden = false;
  const signed = $("#wiz-signed");
  signed.hidden = !s.signed_in;
  signed.textContent = s.signed_in ? `Account ready: ${s.signed_in} ✓` : "";

  $("#wiz-paired").hidden = !s.paired;
  $("#wiz-pair").disabled = !!s.busy;

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
$("#wiz-show-manual").addEventListener("click", () => { $("#wiz-manual").hidden = false; $("#wiz-account-id").focus(); });
$("#wiz-manual-btn").addEventListener("click", () => {
  const accountId = $("#wiz-account-id").value.trim();
  if (!accountId) { $("#wiz-account-id").focus(); return; }
  wizSend({ type: "setup_psn_manual", account_id: accountId, online_id: $("#wiz-online-id").value.trim() });
});
$("#wiz-account-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#wiz-manual-btn").click(); });
$("#wiz-online-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#wiz-manual-btn").click(); });
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

$("#repair").addEventListener("click", () => send({ type: "setup_start", mode: "repair" }));
$("#rerun-setup").addEventListener("click", () => send({ type: "setup_start", mode: "full" }));
$("#forget").addEventListener("click", async () => {
  if (await confirmBox("Sign out and delete the PS5 pairing, your PSN account ID and the PS5 address from this PC? Settings and key maps are kept. You'll need to set up again (including a new PIN from the PS5).")) {
    send({ type: "forget_all" });
  }
});

connect();
