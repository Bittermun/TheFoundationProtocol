// SPDX-License-Identifier: Apache-2.0
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {device: null, ready: false, demo: false, busy: false, balance: null, tag: "", offset: 0, total: 0, pageSize: 6, libraryRequest: 0, readerRequest: 0, current: null, pending: null, published: null};
  const text = (id, value) => { $(id).textContent = value; };
  function notice(message, error = false) {
    text("notice", message);
    $("notice").classList.toggle("error", error);
    $("notice").hidden = !message;
  }
  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function renderTags(container, tags) {
    container.replaceChildren(...tags.map(tag => element("span", "tag", tag)));
  }
  function controls() {
    for (const id of ["publish-button", "roundtrip", "grant", "reader-grant"]) {
      $(id).disabled = !state.ready || state.busy || (id !== "publish-button" && !state.demo);
    }
  }
  async function operation(button, label, action) {
    if (state.busy) return;
    state.busy = true;
    const previous = button.textContent;
    button.textContent = label;
    controls();
    try { await action(); } catch (error) { notice(error.message, true); }
    finally { state.busy = false; button.textContent = previous; controls(); }
  }
  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {...options, cache: "no-store", signal: AbortSignal.timeout(20000)});
    } catch (error) {
      throw new Error(error.name === "TimeoutError" ? "The node took too long to respond. Check the library before publishing again." : "Cannot reach this node. Keep your draft and reconnect when the server is available.");
    }
    let body;
    try { body = await response.json(); } catch { throw new Error("The node returned an unreadable response. Please reconnect and try again."); }
    if (!response.ok) {
      let message = body.detail || body.error || `Request failed (${response.status}).`;
      if (Array.isArray(message)) message = message.map(item => item.msg).join("; ");
      if (response.status === 402) message = state.demo ? "Reading uses 1 credit. Add a demo allowance to continue." : "Reading uses 1 credit. Earn credits through the compute pool to continue.";
      if (response.status === 429) message = "Too many requests. Please wait a minute, then try again.";
      const error = new Error(String(message)); error.status = response.status; throw error;
    }
    return {body, offline: response.headers.get("X-TFP-Offline") === "1"};
  }
  async function signature(message) {
    const bytes = Uint8Array.from(state.device.entropy.match(/../g), h => parseInt(h, 16));
    const key = await crypto.subtle.importKey("raw", bytes, {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
    const signed = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
    return Array.from(new Uint8Array(signed), b => b.toString(16).padStart(2, "0")).join("");
  }
  async function post(path, payload, message) {
    const headers = {"Content-Type": "application/json"};
    if (message) headers["X-Device-Sig"] = await signature(message);
    return (await api(path, {method: "POST", headers, body: JSON.stringify(payload)})).body;
  }
  function device() {
    const raw = localStorage.getItem("tfp_device");
    if (raw) {
      let saved;
      try { saved = JSON.parse(raw); } catch { throw new Error("The saved browser identity is unreadable. Back up browser data before clearing the tfp_device storage entry."); }
      if (!saved || typeof saved.id !== "string" || !/^[a-zA-Z0-9_-]{1,120}$/.test(saved.id) || !/^[a-f0-9]{64}$/i.test(saved.entropy)) throw new Error("The saved browser identity is invalid. Your stored identity has been left unchanged.");
      return saved;
    }
    const entropy = Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, "0")).join("");
    const saved = {id: `web-${entropy.slice(0, 12)}`, entropy};
    localStorage.setItem("tfp_device", JSON.stringify(saved));
    return saved;
  }
  function connected(online) {
    $("connection-dot").classList.toggle("online", online);
    text("connection-label", online ? "Node connected" : "Node unavailable");
    text("connection-detail", online ? "Connected to this server" : "Reconnect to refresh");
    if (!online) { state.ready = false; text("mode-badge", "OFFLINE"); controls(); }
  }
  async function metrics() {
    const {body: status} = await api("/api/status");
    state.demo = status.runtime_mode === "demo";
    text("mode-badge", state.demo ? "DEMO NODE" : "RESTRICTED NODE");
    text("stat-content", status.content_items ?? "—");
    text("nav-count", status.content_items ?? "—");
    text("stat-mode", status.runtime_mode ?? "Restricted");
    text("stat-tasks", status.tasks?.open ?? "—");
    text("stat-completed", status.tasks?.completed ?? "—");
    const results = await Promise.allSettled([
      api(`/api/device/${encodeURIComponent(state.device.id)}`),
      state.demo ? api("/api/devices?limit=1") : Promise.resolve({body: {}})
    ]);
    if (results[0].status === "fulfilled") {
      const info = results[0].value.body;
      state.balance = info.credits_in_memory ?? info.credits_balance ?? 0;
      text("stat-credits", state.balance);
    } else { state.balance = null; text("stat-credits", "—"); }
    text("stat-devices", results[1].status === "fulfilled" ? results[1].value.body.total_enrolled ?? "—" : "—");
    connected(true);
    controls();
  }
  async function refreshMetrics() {
    try { await metrics(); } catch { connected(false); for (const id of ["stat-content", "stat-devices", "stat-credits", "stat-tasks", "stat-completed"]) text(id, "—"); }
  }
  async function connect() {
    try {
      if (!crypto.subtle) throw new Error("Open this demo on localhost or HTTPS so the browser can sign requests.");
      state.device = device();
      await post("/api/enroll", {device_id: state.device.id, puf_entropy_hex: state.device.entropy});
      text("device-id", state.device.id);
      await metrics();
      state.ready = true;
      controls();
      notice("");
      await library();
    } catch (error) { connected(false); notice(error.message, true); }
  }
  function card(item) {
    const button = element("button", "note-card");
    button.type = "button";
    button.setAttribute("aria-label", `Read ${item.title || "Untitled note"}`);
    const head = element("div", "card-head");
    head.append(element("span", "note-icon", "Aa"), element("span", "card-type", "NOTE"));
    const tags = element("div", "tags"); renderTags(tags, (item.tags || []).slice(0, 3));
    const bottom = element("div", "card-bottom");
    bottom.append(element("span", "", `${item.root_hash.slice(0, 12)}…`), element("span", "card-arrow", "↗"));
    button.append(head, element("h3", "", item.title || "Untitled note"), tags, bottom);
    button.addEventListener("click", () => read(item));
    return button;
  }
  async function library() {
    const request = ++state.libraryRequest;
    $("library").setAttribute("aria-busy", "true");
    const params = new URLSearchParams({limit: state.pageSize, offset: state.offset});
    if (state.tag) params.set("tag", state.tag);
    try {
      const {body} = await api(`/api/content?${params}`);
      if (request !== state.libraryRequest) return;
      state.total = body.total;
      if (state.offset && state.offset >= body.total) { state.offset = 0; return library(); }
      text("library-count", body.total);
      $("library").replaceChildren(...body.items.map(card));
      if (!body.items.length) {
        const empty = element("div", "empty");
        empty.append(element("strong", "", state.tag ? "No notes with this tag yet." : "Your commons starts here."), element("p", "", state.tag ? "Try another tag, or publish the first note on this topic." : "Publish a note to add something useful to the library."));
        $("library").append(empty);
      }
      text("page-label", body.total ? `Showing ${state.offset + 1}–${state.offset + body.items.length} of ${body.total}` : "0 notes");
      $("previous").disabled = state.offset === 0;
      $("next").disabled = state.offset + state.pageSize >= body.total;
    } catch (error) {
      if (request !== state.libraryRequest) return;
      $("library").replaceChildren(element("p", "empty", error.message));
      text("library-count", "—"); text("page-label", "Library unavailable");
      $("previous").disabled = $("next").disabled = true;
    } finally { if (request === state.libraryRequest) $("library").removeAttribute("aria-busy"); }
  }
  function filter(tag) {
    state.tag = tag.trim().toLowerCase(); state.offset = 0;
    $("search").value = state.tag;
    document.querySelectorAll("[data-tag]").forEach(button => {
      const selected = button.dataset.tag === state.tag;
      button.classList.toggle("selected", selected); button.setAttribute("aria-pressed", selected);
    });
    library();
  }
  async function grant() {
    if (!state.demo) throw new Error("Demo credit grants are unavailable on this node. Use the compute pool.");
    const task = `web-demo-${crypto.randomUUID()}`;
    const result = await post("/api/earn", {device_id: state.device.id, task_id: task}, `${state.device.id}:${task}`);
    await refreshMetrics();
    return result;
  }
  async function retrieve(root) {
    if (!state.device) throw new Error("Connect to the node before reading a note.");
    return api(`/api/get/${encodeURIComponent(root)}?device_id=${encodeURIComponent(state.device.id)}`, {headers: {"X-Device-Sig": await signature(`${state.device.id}:${root}`)}});
  }
  function showContent(data, offline = false) {
    state.current = data;
    text("reader-title", data.title || "Untitled note"); renderTags($("reader-tags"), data.tags || []);
    text("reader-text", data.text); text("reader-hash", data.root_hash);
    text("reader-status", offline ? "Saved copy · You are offline. No new credit spent." : "Retrieved from this node · 1 credit spent");
    $("reader-details").hidden = false; $("reader-grant").hidden = true;
  }
  async function read(item) {
    const request = ++state.readerRequest;
    state.pending = item; state.current = null;
    text("reader-title", item.title || "Opening note…"); text("reader-text", ""); text("reader-status", "Retrieving content…");
    $("reader-tags").replaceChildren(); $("reader-details").hidden = true; $("reader-grant").hidden = true;
    if (!$("reader").open) $("reader").showModal();
    try {
      const result = await retrieve(item.root_hash);
      if (request !== state.readerRequest) return;
      showContent(result.body, result.offline); await refreshMetrics();
    } catch (error) {
      if (request !== state.readerRequest) return;
      text("reader-status", error.message);
      $("reader-grant").hidden = error.status !== 402 || !state.demo;
    }
  }
  async function publish(payload) {
    return post("/api/publish", {...payload, device_id: state.device.id}, `${state.device.id}:${payload.title}`);
  }
  async function roundtrip() {
    const steps = ["1/3 · Preparing a demo allowance…", "2/3 · Publishing a sample note…", "3/3 · Retrieving and comparing the text…"];
    text("roundtrip-status", steps[0]);
    if (state.balance === null || state.balance < 1) await grant();
    const payload = {title: "A note to the commons", text: "Useful knowledge begins with someone willing to share it.\n\nThis note traveled from your browser to a Foundation node, received a content fingerprint, and came back through the retrieval API.\n\nTry changing these words by publishing a note of your own.", tags: ["community", "demo"]};
    text("roundtrip-status", steps[1]);
    const published = await publish(payload);
    text("roundtrip-status", steps[2]);
    const {body, offline} = await retrieve(published.root_hash);
    if (offline || body.text !== payload.text || body.root_hash !== published.root_hash || body.sha3 !== published.root_hash) throw new Error("Round-trip verification failed: the retrieved content did not match the published note.");
    text("roundtrip-status", "Round trip verified · The retrieved text matches what you published.");
    notice("Round trip verified. Your sample is now in the library. Publish your own note to try it again.");
    state.tag = ""; filter(""); await refreshMetrics();
    showContent(body); text("reader-status", "Round trip verified · Exact text match with your published note");
    $("reader").showModal();
  }
  function saveDraft() {
    text("character-count", `${$("text").value.length.toLocaleString()} characters`);
    try {
      localStorage.setItem("tfp_draft", JSON.stringify({title: $("title").value, text: $("text").value, tags: $("tags").value}));
      text("draft-status", "Draft saved in this browser.");
    } catch { text("draft-status", "Draft could not be saved. Keep this tab open."); }
  }
  function restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem("tfp_draft") || "{}");
      for (const id of ["title", "text", "tags"]) if (typeof draft?.[id] === "string") $(id).value = draft[id];
      text("character-count", `${$("text").value.length.toLocaleString()} characters`);
    } catch { text("draft-status", "Saved draft unavailable. You can still write a note."); }
  }
  function route(focus = false) {
    const requested = location.hash.slice(1);
    const view = ["library", "publish", "node", "about"].includes(requested) ? requested : "library";
    document.querySelectorAll(".view").forEach(section => { section.hidden = section.id !== `view-${view}`; });
    document.querySelectorAll("[data-view]").forEach(link => {
      const active = link.dataset.view === view;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    text("breadcrumb", {library: "Library", publish: "Publish", node: "Your node", about: "How it works"}[view]);
    if (focus) { $("main").focus(); window.scrollTo(0, 0); }
  }
  async function copy(value, button) {
    if (!value) return;
    const previous = button.textContent;
    try { await navigator.clipboard.writeText(value); button.textContent = "Copied"; }
    catch { button.textContent = "Select fingerprint to copy"; }
    setTimeout(() => { button.textContent = previous; }, 2500);
  }
  $("publish-form").addEventListener("submit", event => {
    event.preventDefault();
    operation($("publish-button"), "Publishing…", async () => {
      const title = $("title").value.trim(); const body = $("text").value;
      if (!title || !body.trim()) throw new Error("Add a title and some text before publishing.");
      const payload = {title, text: body, tags: [...new Set($("tags").value.split(",").map(t => t.trim().toLowerCase()).filter(Boolean))]};
      const result = await publish(payload);
      state.published = result;
      text("published-title", result.title); text("published-hash", result.root_hash);
      $("publish-result").hidden = false;
      notice("Your note is published. You can read it or copy its fingerprint below.");
      try { localStorage.removeItem("tfp_draft"); } catch { /* Publishing succeeds even when storage is unavailable. */ }
      text("draft-status", "Published. Edit to create another version.");
      await Promise.all([library(), refreshMetrics()]);
      $("publish-result").scrollIntoView({behavior: "smooth", block: "nearest"});
    });
  });
  $("roundtrip").addEventListener("click", () => operation($("roundtrip"), "Running the round trip…", async () => {
    try { await roundtrip(); } catch (error) { text("roundtrip-status", "Round trip incomplete. You can retry when the node is ready."); throw error; }
  }));
  $("grant").addEventListener("click", () => operation($("grant"), "Adding credits…", async () => { const result = await grant(); notice(`Added ${result.credits_earned} demo credits. This is a test allowance, not verified compute.`); }));
  $("reader-grant").addEventListener("click", () => operation($("reader-grant"), "Adding credits…", async () => { try { await grant(); await read(state.pending); } catch (error) { text("reader-status", error.message); throw error; } }));
  $("read-published").addEventListener("click", () => { if (state.published) read(state.published); });
  $("copy-published").addEventListener("click", () => copy(state.published?.root_hash, $("copy-published")));
  $("copy-hash").addEventListener("click", () => copy(state.current?.root_hash, $("copy-hash")));
  $("download").addEventListener("click", () => {
    if (!state.current) return;
    const link = document.createElement("a"); const url = URL.createObjectURL(new Blob([state.current.text], {type: "text/plain;charset=utf-8"}));
    link.href = url; link.download = `foundation-${state.current.root_hash.slice(0, 12)}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("close-reader").addEventListener("click", () => $("reader").close());
  $("reader").addEventListener("close", () => { state.readerRequest++; });
  $("reader").addEventListener("click", event => { if (event.target === $("reader")) { const rect = $("reader").getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $("reader").close(); } });
  $("refresh").addEventListener("click", () => { library(); refreshMetrics(); });
  $("reconnect").addEventListener("click", connect);
  $("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.pageSize); library(); });
  $("next").addEventListener("click", () => { if (state.offset + state.pageSize < state.total) { state.offset += state.pageSize; library(); } });
  $("search-form").addEventListener("submit", event => { event.preventDefault(); filter($("search").value); });
  $("search").addEventListener("search", () => { if (!$("search").value) filter(""); });
  $("hash-form").addEventListener("submit", event => { event.preventDefault(); read({root_hash: $("lookup-hash").value.trim().toLowerCase()}); });
  document.querySelectorAll("[data-tag]").forEach(button => button.addEventListener("click", () => filter(button.dataset.tag)));
  for (const id of ["title", "text", "tags"]) $(id).addEventListener("input", saveDraft);
  window.addEventListener("hashchange", () => route(true));
  window.addEventListener("online", connect);
  window.addEventListener("offline", () => { connected(false); notice("You are offline. Previously opened notes may be available as saved copies. Your draft stays in this browser."); });
  setInterval(() => { if (state.ready && !document.hidden && !state.busy) refreshMetrics(); }, 15000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(() => { /* Online use remains available. */ });
  restoreDraft(); route(); connect();
})();
