/* Ask Ziira chat (loaded lazily by assistant.js). Vanilla JS, no framework. Talks to the Ziira API over fetch + a streamed (SSE) reply.
   Contract: GET <api>/api/v1/public/assistant/config and POST <api>/api/v1/public/assistant/stream (docs/marketing-site.md).
   Nothing is ever invented here: every word of an answer comes from the API; when it fails the visitor gets a plain message and links. */
(function () {
  var MAX = 500, WARN = 400, HISTORY = 6, STORE = "zr-assistant-chat";
  var DEFAULT_CHIPS = ["What does Ziira cost?", "Is Ziira right for my kind of business?", "How do the daily checks work?", "Can it work with the system I already use?"];
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var st = null; // state of the open chat

  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function svg(path, cls) { var s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false"); if (cls) s.setAttribute("class", cls); s.innerHTML = path; return s; }
  var SPARK = '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" fill="currentColor"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" fill="currentColor"/>';

  function build() {
    var root = el("div", "zr-root");
    root.innerHTML =
      '<div class="zr-backdrop" data-close></div>' +
      '<div class="zr-dialog" role="dialog" aria-modal="true" aria-labelledby="zr-title" tabindex="-1">' +
      '<div class="zr-phone">' +
      '<div class="zr-status" aria-hidden="true"><span class="zr-time"></span><span class="zr-notch"></span><span class="zr-sys">' +
      '<svg viewBox="0 0 18 12"><rect x="0" y="8" width="3" height="4" rx=".8"/><rect x="5" y="5.5" width="3" height="6.5" rx=".8"/><rect x="10" y="3" width="3" height="9" rx=".8"/><rect x="15" y="0" width="3" height="12" rx=".8"/></svg>' +
      '<svg viewBox="0 0 16 12"><path d="M8 11.2a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6zM3.9 7.1a5.8 5.8 0 0 1 8.2 0l-1.1 1.1a4.2 4.2 0 0 0-6 0zM1 4.2a9.9 9.9 0 0 1 14 0l-1.1 1.1a8.3 8.3 0 0 0-11.8 0z"/></svg>' +
      '<svg viewBox="0 0 27 12"><rect x=".5" y=".5" width="22" height="11" rx="3.2" fill="none" stroke="currentColor"/><rect x="2" y="2" width="16" height="8" rx="1.8"/><rect x="24" y="4" width="2.2" height="4" rx="1"/></svg></span></div>' +
      '<header class="zr-head"><span class="zr-av" aria-hidden="true"></span><div class="zr-who"><h2 id="zr-title">Ask Ziira</h2><p><i class="zr-dot" aria-hidden="true"></i>online</p></div><span class="zr-badge">AI</span>' +
      '<button type="button" class="zr-x" data-close aria-label="Close Ask Ziira"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" fill="none"/></svg></button></header>' +
      '<div class="zr-log" role="log" aria-live="polite" aria-relevant="additions text" tabindex="0" aria-label="Conversation with Ziira"></div>' +
      '<div class="zr-chips" aria-label="Suggested questions"></div>' +
      '<form class="zr-form" autocomplete="off"><div class="zr-field"><label class="zr-sr" for="zr-input">Your question</label>' +
      '<textarea id="zr-input" rows="1" maxlength="' + MAX + '" placeholder="Ask about Ziira" enterkeyhint="send"></textarea><span class="zr-count" aria-live="off"></span></div>' +
      '<button type="submit" class="zr-send" aria-label="Send"></button></form>' +
      '<p class="zr-privacy">Do not share personal or business data here.</p>' +
      '<span class="zr-home" aria-hidden="true"></span>' +
      '</div></div>';
    root.querySelector(".zr-av").appendChild(svg(SPARK));
    return root;
  }

  var SEND = '<path d="M4 12l16-8-6 16-3-7z" fill="currentColor"/>', STOP = '<rect x="6.5" y="6.5" width="11" height="11" rx="2.5" fill="currentColor"/>';

  function clock() { var n = new Date(); return (n.getHours() < 10 ? "0" : "") + n.getHours() + ":" + (n.getMinutes() < 10 ? "0" : "") + n.getMinutes(); }

  function save() { try { sessionStorage.setItem(STORE, JSON.stringify(st.msgs.slice(-40))); } catch (e) {} }
  function restore() { try { var j = JSON.parse(sessionStorage.getItem(STORE) || "[]"); return Array.isArray(j) ? j : []; } catch (e) { return []; } }

  function scroll() { var l = st.log; l.scrollTop = l.scrollHeight; }
  function bubble(who) {
    var row = el("div", "zr-row zr-" + who), b = el("div", "zr-bubble");
    row.appendChild(b); st.log.appendChild(row); return b;
  }
  function addText(b, line, instant) {
    var m = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line), item = !!m, txt = (m ? m[1] : line).replace(/\*\*/g, "");
    var holder;
    if (item) { var ul = b.lastElementChild && b.lastElementChild.tagName === "UL" ? b.lastElementChild : b.appendChild(el("ul")); holder = ul.appendChild(el("li")); }
    else holder = b.appendChild(el("p"));
    if (instant) { holder.textContent = txt; return null; }
    return { node: holder, words: txt.split(/(\s+)/) };
  }
  function linkCards(b, items) {
    var box = el("div", "zr-links");
    items.slice(0, 4).forEach(function (it) {
      if (!it || typeof it.href !== "string" || typeof it.title !== "string") return;
      var u; try { u = new URL(it.href, location.href); } catch (e) { return; }
      if (!/^https?:$/.test(u.protocol)) return;
      var a = el("a", "zr-card"); a.href = u.href; a.appendChild(el("span", null, it.title));
      a.appendChild(svg('<path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'));
      if (u.origin !== location.origin) { a.target = "_blank"; a.rel = "noopener"; }
      box.appendChild(a);
    });
    if (box.children.length) b.parentNode.after(box);
  }

  function setBusy(on) {
    st.busy = on;
    var s = st.send; s.innerHTML = ""; s.appendChild(svg(on ? STOP : SEND)); s.setAttribute("aria-label", on ? "Stop" : "Send"); s.classList.toggle("zr-stop", on);
    st.root.querySelector(".zr-dialog").setAttribute("aria-busy", on ? "true" : "false");
  }

  /* ---- typing out: one queue of events, played one at a time ---- */
  function play() {
    if (st.playing) return;
    var ev = st.queue.shift();
    if (!ev) { if (st.finished) finish(); return; }
    st.playing = true;
    var cur = st.cur;
    if (ev.t === "text") {
      hideTyping();
      var piece = addText(cur.bubble, ev.text, reduced || st.skip);
      cur.text.push(ev.text);
      if (!piece) { st.playing = false; scroll(); return play(); }
      var i = 0, w = piece.words;
      (function tick() {
        if (st.skip || !st.root.isConnected) { piece.node.textContent = w.join(""); st.playing = false; scroll(); return play(); }
        i += 2; piece.node.textContent = w.slice(0, i).join(""); scroll();
        if (i >= w.length) { st.playing = false; return setTimeout(play, 120); }
        st.timer = setTimeout(tick, 32);
      })();
    } else if (ev.t === "links") { linkCards(cur.bubble, ev.items); cur.links = ev.items; st.playing = false; scroll(); play(); }
    else { st.playing = false; play(); }
  }
  function showTyping(label) {
    var c = st.cur;
    if (!c.typing) { c.typing = el("div", "zr-typing"); c.typing.appendChild(el("span", "zr-dots")); c.typing.firstChild.innerHTML = "<i></i><i></i><i></i>"; c.status = el("span", "zr-statusline"); c.typing.appendChild(c.status); c.bubble.parentNode.after(c.typing); }
    c.status.textContent = label || c.status.textContent || "";
    scroll();
  }
  function hideTyping() { var c = st.cur; if (c && c.typing) { c.typing.remove(); c.typing = null; } }

  function finish() {
    var c = st.cur; hideTyping();
    if (c.text.length) { st.msgs.push({ role: "assistant", text: c.text.join(" "), links: c.links }); save(); }
    else if (!c.failed && c.bubble.parentNode) c.bubble.parentNode.remove();
    setBusy(false); st.cur = null; st.skip = false; st.input.focus({ preventScroll: true });
  }

  function fail(reason, message, retryAfter, text) {
    var c = st.cur; hideTyping(); c.failed = true;
    if (!c.text.length && c.bubble.parentNode) c.bubble.parentNode.remove();
    var row = el("div", "zr-row zr-ziira zr-err"), b = el("div", "zr-bubble");
    var defaults = { off: "Ask Ziira is not available right now.", busy: "Ask Ziira is busy right now. Please try again in a moment.", budget: "Ask Ziira has reached its limit for now.", provider_failed: "Ask Ziira could not answer just now.", too_long: "That question is too long. Please shorten it and try again." };
    b.appendChild(el("p", null, message || defaults[reason] || "Ask Ziira could not answer just now."));
    row.appendChild(b); st.log.appendChild(row);
    var acts = el("div", "zr-links");
    if (reason !== "off" && reason !== "budget" && reason !== "too_long") {
      var retry = el("button", "zr-card zr-retry"); retry.type = "button"; retry.appendChild(el("span", null, "Try again"));
      var wait = Math.max(0, Math.min(60, Number(retryAfter) || 0));
      var lbl = retry.firstChild;
      if (wait) { retry.disabled = true; (function count() { lbl.textContent = wait > 0 ? "Try again in " + wait + "s" : "Try again"; if (wait-- > 0) setTimeout(count, 1000); else retry.disabled = false; })(); }
      retry.addEventListener("click", function () { var prev = row.previousElementSibling; if (prev && prev.classList.contains("zr-user")) prev.remove(); row.remove(); acts.remove(); if (st.msgs.length && st.msgs[st.msgs.length - 1].role === "user") st.msgs.pop(); send(text); });
      acts.appendChild(retry);
    }
    [["Open pricing", st.opts.pricing], ["Contact us", st.opts.contact]].forEach(function (p) {
      if (!p[1]) return; var a = el("a", "zr-card"); a.href = p[1]; a.appendChild(el("span", null, p[0])); acts.appendChild(a);
    });
    st.log.appendChild(acts);
    st.queue = []; st.finished = true; st.playing = false; finish(); scroll();
  }

  function parse(chunk, onEvent) {
    chunk.split(/\r?\n\r?\n/).forEach(function (blk) {
      var name = "message", data = [];
      blk.split(/\r?\n/).forEach(function (l) {
        if (l.indexOf("event:") === 0) name = l.slice(6).trim(); else if (l.indexOf("data:") === 0) data.push(l.slice(5).replace(/^ /, ""));
      });
      if (!data.length) return;
      var j; try { j = JSON.parse(data.join("\n")); } catch (e) { return; }
      onEvent(name, j);
    });
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || st.busy) return;
    if (text.length > MAX) text = text.slice(0, MAX);
    var hist = st.msgs.slice(-HISTORY).map(function (m) { return { role: m.role, text: m.text }; });
    st.msgs.push({ role: "user", text: text });
    var u = bubble("user"); u.textContent = text; u.parentNode.classList.add("zr-in");
    st.chips.hidden = true; st.input.value = ""; autosize();
    save();
    var b = bubble("ziira"); b.parentNode.classList.add("zr-in");
    st.cur = { bubble: b, text: [], links: null, typing: null, status: null, failed: false };
    st.queue = []; st.finished = false; st.skip = false;
    setBusy(true); showTyping(""); scroll();
    var ctl = typeof AbortController === "function" ? new AbortController() : null; st.abort = ctl;
    var cur = st.cur, got = false, ended = false;
    fetch(st.opts.api + "/api/v1/public/assistant/stream", {
      method: "POST", credentials: "omit", signal: ctl ? ctl.signal : undefined,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message: text, history: hist, page: location.pathname, lang: "en" }),
    }).then(function (r) {
      if (!r.ok || !r.body) throw new Error("http " + r.status);
      var rd = r.body.getReader(), dec = new TextDecoder(), buf = "";
      function onEvent(name, j) {
        if (cur !== st.cur) return;
        if (name === "status") { showTyping(String(j.text || "")); }
        else if (name === "text" && j.text) { got = true; st.queue.push({ t: "text", text: String(j.text) }); play(); }
        else if (name === "links" && j.items) { st.queue.push({ t: "links", items: j.items }); play(); }
        else if (name === "done") { ended = true; st.finished = true; play(); }
        else if (name === "error") { ended = true; fail(j.reason, j.message, j.retry_after, text); }
      }
      return (function pump() {
        return rd.read().then(function (x) {
          if (x.done) { if (buf.trim()) parse(buf, onEvent); if (!ended && cur === st.cur) { ended = true; if (got) { st.finished = true; play(); } else fail("provider_failed", "", 0, text); } return; }
          buf += dec.decode(x.value, { stream: true });
          var cut = buf.lastIndexOf("\n\n");
          if (cut >= 0) { var part = buf.slice(0, cut + 2); buf = buf.slice(cut + 2); parse(part, onEvent); }
          return pump();
        });
      })();
    }).catch(function (e) {
      if (cur !== st.cur || ended) return;
      if (e && e.name === "AbortError") { ended = true; st.finished = true; if (cur.text.length || st.queue.length) { st.queue.push({ t: "x" }); play(); } else { cur.bubble.parentNode.remove(); st.msgs.pop(); st.queue = []; finish(); } return; }
      fail(got ? "provider_failed" : "off", got ? "The answer was cut off. Please try again." : "Ask Ziira cannot be reached right now.", 0, text);
    });
  }

  function autosize() {
    var i = st.input; i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 96) + "px";
    var n = i.value.length; st.count.textContent = n >= WARN ? n + "/" + MAX : ""; st.count.classList.toggle("zr-full", n >= MAX);
    st.send.disabled = !st.busy && !i.value.trim();
  }

  function focusables() { return Array.prototype.filter.call(st.root.querySelectorAll('button, a[href], textarea, [tabindex="0"]'), function (n) { return !n.disabled && !n.hidden && n.offsetParent !== null; }); }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab") return;
    var f = focusables(); if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === st.dialog)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function open(opts) {
    if (st) return;
    var root = build();
    st = { opts: opts, root: root, msgs: restore(), queue: [], busy: false, timer: 0, prevInert: [] };
    document.body.appendChild(root);
    st.dialog = root.querySelector(".zr-dialog"); st.log = root.querySelector(".zr-log"); st.chips = root.querySelector(".zr-chips");
    st.input = root.querySelector("textarea"); st.count = root.querySelector(".zr-count"); st.send = root.querySelector(".zr-send");
    var tm = root.querySelector(".zr-time"); tm.textContent = clock(); st.clock = setInterval(function () { tm.textContent = clock(); }, 20000);
    var cfg = opts.config || {};
    // history
    var greet = bubble("ziira"); greet.parentNode.classList.add("zr-static");
    greet.appendChild(el("p", null, cfg.greeting || "Hi, I am Ziira. Ask me about our plans, what Ziira does, or whether it fits your business."));
    st.msgs.forEach(function (m) {
      var b = bubble(m.role === "user" ? "user" : "ziira"); b.parentNode.classList.add("zr-static");
      if (m.role === "user") b.textContent = m.text; else { addText(b, m.text, true); if (m.links) linkCards(b, m.links); }
    });
    // chips
    var chips = (Array.isArray(cfg.suggestions) && cfg.suggestions.length ? cfg.suggestions : DEFAULT_CHIPS).slice(0, 5);
    chips.forEach(function (c) { var b = el("button", "zr-chip", String(c)); b.type = "button"; b.addEventListener("click", function () { send(String(c)); }); st.chips.appendChild(b); });
    st.chips.hidden = st.msgs.length > 0;
    setBusy(false); autosize();

    root.addEventListener("click", function (e) {
      if (e.target.closest("[data-close]")) return close();
      if (st.playing && e.target.closest(".zr-bubble")) st.skip = true;
    });
    st.send.addEventListener("click", function (e) { if (st.busy) { e.preventDefault(); stop(); } });
    root.querySelector("form").addEventListener("submit", function (e) { e.preventDefault(); if (!st.busy) send(st.input.value); });
    st.input.addEventListener("input", autosize);
    st.input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!st.busy) send(st.input.value); } });
    root.addEventListener("keydown", onKey);

    // keep the page behind out of reach while the chat is open
    Array.prototype.forEach.call(document.body.children, function (n) { if (n !== root && n.tagName !== "SCRIPT" && !n.inert) { n.inert = true; st.prevInert.push(n); } });
    document.documentElement.classList.add("zr-open");
    if (opts.fab) opts.fab.classList.add("zr-hide");
    requestAnimationFrame(function () { requestAnimationFrame(function () { root.classList.add("zr-show"); st.log.scrollTop = st.log.scrollHeight; (st.msgs.length ? st.input : st.input).focus({ preventScroll: true }); }); });
  }

  function stop() { if (st.abort) st.abort.abort(); }

  function close() {
    if (!st) return;
    var s = st; st = null;
    if (s.abort) s.abort.abort();
    clearTimeout(s.timer); clearInterval(s.clock);
    s.root.classList.remove("zr-show");
    s.prevInert.forEach(function (n) { n.inert = false; });
    document.documentElement.classList.remove("zr-open");
    if (s.opts.fab) s.opts.fab.classList.remove("zr-hide");
    var done = function () { s.root.remove(); };
    if (reduced) done(); else setTimeout(done, 260);
    var back = s.opts.opener && s.opts.opener.isConnected ? s.opts.opener : s.opts.fab;
    if (back) back.focus({ preventScroll: true });
  }

  window.ZiiraChat = { open: open, close: close };
})();
