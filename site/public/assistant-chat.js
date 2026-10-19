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
      '<header class="zr-head"><button type="button" class="zr-hbtn zr-back" data-close aria-label="Close Ask Ziira"></button><span class="zr-av" aria-hidden="true"></span><div class="zr-who"><h2 id="zr-title">Ziira</h2><p class="zr-sub">online</p></div>' +
      '<button type="button" class="zr-hbtn zr-kebab" aria-label="Menu" aria-haspopup="menu" aria-expanded="false"></button>' +
      '<div class="zr-menu" role="menu" hidden><button type="button" role="menuitem" data-new>New chat</button><button type="button" role="menuitem" data-close>Close</button></div></header>' +
      '<div class="zr-log" role="log" aria-live="polite" aria-relevant="additions text" tabindex="0" aria-label="Conversation with Ziira"></div>' +
      '<form class="zr-form" autocomplete="off"><div class="zr-field"><span class="zr-ico zr-emoji" aria-hidden="true"></span><label class="zr-sr" for="zr-input">Your message</label>' +
      '<textarea id="zr-input" rows="1" maxlength="' + MAX + '" placeholder="Message" enterkeyhint="send"></textarea><span class="zr-ico zr-attach" aria-hidden="true"></span><span class="zr-count" aria-live="off"></span></div>' +
      '<button type="submit" class="zr-send" aria-label="Send"></button></form>' +
      '<p class="zr-privacy">Do not share personal or business data here.</p>' +
      '<span class="zr-home" aria-hidden="true"></span>' +
      '</div></div>';
    root.querySelector(".zr-av").appendChild(svg(SPARK));
    root.querySelector(".zr-back").appendChild(svg(ICON.back, "zr-i"));
    root.querySelector(".zr-kebab").appendChild(svg(ICON.kebab, "zr-i"));
    root.querySelector(".zr-emoji").appendChild(svg(ICON.smile)); root.querySelector(".zr-attach").appendChild(svg(ICON.clip));
    return root;
  }

  var ICON = {
    back: '<path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20z" fill="currentColor"/>',
    kebab: '<circle cx="12" cy="5.5" r="1.9" fill="currentColor"/><circle cx="12" cy="12" r="1.9" fill="currentColor"/><circle cx="12" cy="18.5" r="1.9" fill="currentColor"/>',
    smile: '<circle cx="12" cy="12" r="9"/><path d="M8.2 14a4.6 4.6 0 0 0 7.6 0"/><path d="M9 9.6h.01M15 9.6h.01" stroke-width="2.4"/>',
    clip: '<path d="M20 11.5l-7.6 7.6a5 5 0 0 1-7-7l8.3-8.3a3.3 3.3 0 0 1 4.7 4.7l-8.3 8.3a1.7 1.7 0 0 1-2.4-2.4l7.4-7.4"/>',
    mic: '<path d="M12 14.5a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5.5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5.5a6.5 6.5 0 0 0 5.75 6.45V21h1.5v-3.05A6.5 6.5 0 0 0 18.5 11.5z" fill="currentColor"/>',
    send: '<path d="M3.4 20.4l17.45-7.48a1 1 0 0 0 0-1.84L3.4 3.6a.99.99 0 0 0-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.88c-.5.07-.87.5-.87 1l.01 4.61c0 .71.73 1.2 1.39.91z" fill="currentColor"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor"/>',
    tick: '<path class="zr-ta" d="M1 6l3.2 3.2L10 1.6"/><path d="M6 8.4l1 1L13.8 1.6"/>',
  };
  var SEND = ICON.send, STOP = ICON.stop;

  function clock() { var n = new Date(); return (n.getHours() < 10 ? "0" : "") + n.getHours() + ":" + (n.getMinutes() < 10 ? "0" : "") + n.getMinutes(); }

  function save() { try { sessionStorage.setItem(STORE, JSON.stringify(st.msgs.slice(-40))); } catch (e) {} }
  function restore() { try { var j = JSON.parse(sessionStorage.getItem(STORE) || "[]"); return Array.isArray(j) ? j : []; } catch (e) { return []; } }

  function scroll() { var l = st.log; l.scrollTop = l.scrollHeight; }
  function bubble(who) {
    var rows = st.log.querySelectorAll(":scope > .zr-row"), prev = rows[rows.length - 1];
    var first = !prev || prev.classList.contains("zr-user") !== (who === "user");
    var row = el("div", "zr-row zr-" + who + (first ? " zr-first" : "")), b = el("div", "zr-bubble");
    row.appendChild(b); st.log.appendChild(row); return b;
  }
  function tickIcon() { var t = svg(ICON.tick, "zr-ticks"); t.setAttribute("viewBox", "0 0 16 11"); return t; }
  /* The little time (and, for the visitor's own messages, the ticks) at the bottom right of a bubble. */
  function stamp(b, at, tick) {
    if (b.querySelector(":scope > .zr-meta")) return;
    var m = el("span", "zr-meta");
    m.appendChild(el("span", null, at || clock()));
    if (tick) { m.appendChild(tickIcon()); m.classList.add(tick === "read" ? "zr-read" : "zr-sent"); }
    b.appendChild(m);
  }
  function put(b, node) { var m = b.querySelector(":scope > .zr-meta"); return m ? b.insertBefore(node, m) : b.appendChild(node); }
  function addText(b, line, instant) {
    var m = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line), item = !!m, txt = (m ? m[1] : line).replace(/\*\*/g, "");
    var holder, last = b.lastElementChild;
    if (last && last.classList.contains("zr-meta")) last = last.previousElementSibling;
    if (item) { var ul = last && last.tagName === "UL" ? last : put(b, el("ul")); holder = ul.appendChild(el("li")); }
    else holder = put(b, el("p"));
    if (b.parentNode.classList.contains("zr-ziira")) stamp(b, b._at);
    if (instant) { holder.textContent = txt; return null; }
    return { node: holder, words: txt.split(/(\s+)/) };
  }
  function linkCards(b, items) {
    var box = el("div", "zr-links");
    items.slice(0, 4).forEach(function (it) {
      if (!it || typeof it.href !== "string" || typeof it.title !== "string") return;
      var u; try { u = new URL(it.href, location.href); } catch (e) { return; }
      if (!/^https?:$/.test(u.protocol)) return;
      var a = el("a", "zr-card"), sp = el("span", null, it.title); a.href = u.href;
      sp.appendChild(el("small", null, u.host + u.pathname.replace(/\/$/, "")));
      a.appendChild(sp);
      if (u.origin !== location.origin) { a.target = "_blank"; a.rel = "noopener"; }
      box.appendChild(a);
    });
    if (box.children.length) b.parentNode.after(box);
  }
  function setSub(text) { var p = st.root.querySelector(".zr-sub"); if (p && !st.limited) p.textContent = text; }
  function sendIcon() {
    var s = st.send, mode = st.busy ? "stop" : (st.input && st.input.value.trim() ? "send" : "mic");
    if (s.dataset.mode === mode) return;
    s.dataset.mode = mode; s.innerHTML = ""; s.appendChild(svg(ICON[mode]));
    s.setAttribute("aria-label", mode === "stop" ? "Stop" : mode === "send" ? "Send" : "Write a message"); s.classList.toggle("zr-stop", mode === "stop");
  }

  function setBusy(on) {
    st.busy = on; sendIcon();
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
    setSub("typing…");
    c.status.textContent = label || c.status.textContent || "";
    scroll();
  }
  function hideTyping() { var c = st.cur; if (c && c.typing) { c.typing.remove(); c.typing = null; } }

  function finish() {
    var c = st.cur; hideTyping(); setSub("online");
    if (c.text.length) { st.msgs.push({ role: "assistant", text: c.text.join(" "), links: c.links, at: c.bubble._at }); save(); }
    else if (!c.failed && c.bubble.parentNode) c.bubble.parentNode.remove();
    setBusy(false); st.cur = null; st.skip = false; st.input.focus({ preventScroll: true });
  }

  function fail(reason, message, retryAfter, text) {
    var c = st.cur; hideTyping(); c.failed = true;
    if (!c.text.length && c.bubble.parentNode) c.bubble.parentNode.remove();
    var b = bubble("ziira"), row = b.parentNode; row.classList.add("zr-err");
    var defaults = { off: "Ask Ziira is not available right now.", busy: "Ask Ziira is busy right now. Please try again in a moment.", budget: "Ask Ziira has reached its limit for now.", provider_failed: "Ask Ziira could not answer just now.", too_long: "That question is too long. Please shorten it and try again." };
    b.appendChild(el("p", null, message || defaults[reason] || "Ask Ziira could not answer just now.")); stamp(b);
    var acts = el("div", "zr-links");
    if (reason !== "off" && reason !== "budget" && reason !== "too_long") {
      var retry = el("button", "zr-card zr-retry"); retry.type = "button"; retry.appendChild(el("span", null, "Try again"));
      var wait = Math.max(0, Math.min(60, Number(retryAfter) || 0));
      var lbl = retry.firstChild;
      if (wait) { retry.disabled = true; (function count() { lbl.textContent = wait > 0 ? "Try again in " + wait + "s" : "Try again"; if (wait-- > 0) setTimeout(count, 1000); else retry.disabled = false; })(); }
      retry.addEventListener("click", function () { var prev = row.previousElementSibling; if (prev && prev.classList.contains("zr-user")) prev.remove(); row.remove(); acts.remove(); if (st.msgs.length && st.msgs[st.msgs.length - 1].role === "user") st.msgs.pop(); send(text); });
      acts.appendChild(retry);
    }
    var goLimited = reason === "off" || reason === "budget";
    if (!goLimited) [["Open pricing", st.opts.pricing], ["Contact us", st.opts.contact]].forEach(function (p) {
      if (!p[1]) return; var a = el("a", "zr-card"); a.href = p[1]; a.appendChild(el("span", null, p[0])); acts.appendChild(a);
    });
    if (acts.children.length) st.log.appendChild(acts);
    st.queue = []; st.finished = true; st.playing = false; finish();
    if (goLimited) enterLimited(false);
    scroll();
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
    var when = clock();
    st.msgs.push({ role: "user", text: text, at: when });
    var u = bubble("user"); u.appendChild(el("p", null, text)); stamp(u, when, "sent"); u.parentNode.classList.add("zr-in");
    var tickEl = u.querySelector(".zr-meta");
    st.chips.hidden = true; st.input.value = ""; autosize();
    save();
    var b = bubble("ziira"); b.parentNode.classList.add("zr-in"); b._at = clock();
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
      tickEl.classList.remove("zr-sent");                      // delivered: two grey ticks
      var rd = r.body.getReader(), dec = new TextDecoder(), buf = "";
      function onEvent(name, j) {
        if (cur !== st.cur) return;
        if ((name === "status" || name === "text") && !tickEl.classList.contains("zr-read")) { tickEl.classList.remove("zr-sent"); tickEl.classList.add("zr-read"); }   // read: blue ticks
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
    sendIcon();
  }

  function focusables() { return Array.prototype.filter.call(st.root.querySelectorAll('button, a[href], textarea, [tabindex="0"]'), function (n) { return !n.disabled && !n.hidden && n.offsetParent !== null; }); }

  function onKey(e) {
    var openMenu = st.root.querySelector(".zr-menu");
    if (e.key === "Escape") { e.preventDefault(); if (!openMenu.hidden) { st.menuShow(false); st.root.querySelector(".zr-kebab").focus(); } else close(); return; }
    if (e.key !== "Tab" || !st.engaged) return;
    var f = focusables(); if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === st.dialog)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  /* ---- limited mode: the API cannot answer right now (unreachable, no AI provider, a limit reached) ---- */
  var LIMITED_TEXT = "I can't answer live right now. These pages should help:";
  function keyLinks() {
    var o = st.opts;
    return [["Pricing", o.pricing], ["Who it is for", o.who], ["Security", o.security], ["Get started or contact us", o.contact]]
      .filter(function (p) { return p[1]; }).map(function (p) { return { title: p[0], href: p[1] }; });
  }
  function enterLimited(initial) {
    st.limited = true;
    st.chips.hidden = true; st.chips.innerHTML = "";
    var b = bubble("ziira"); b.parentNode.classList.add("zr-static");
    b.appendChild(el("p", null, LIMITED_TEXT)); stamp(b); linkCards(b, keyLinks());
    var nav = st.log.querySelector(".zr-links:last-child"); if (nav) nav.classList.add("zr-keylinks");
    st.input.disabled = true; st.input.placeholder = "Live answers are paused";
    st.root.querySelector(".zr-form").classList.add("zr-off");
    var sub = st.root.querySelector(".zr-sub"); if (sub) sub.textContent = "answers paused";
    if (!initial) scroll();
  }

  var NOTICE = "Ziira's assistant is AI. Answers come from Ziira's public pages. Please do not share personal or business data.";
  /* The conversation screen from the top: date chip, notice, greeting, quick replies, then any earlier messages of this session.
     Auto-open: typing dots for a moment first (the header says "typing…"), then the greeting and the chips. */
  function seed(auto) {
    var cfg = st.cfg, limited = cfg.enabled !== true;
    st.limited = false; st.log.innerHTML = "";
    st.input.disabled = false; st.input.placeholder = "Message"; st.root.querySelector(".zr-form").classList.remove("zr-off");
    st.log.appendChild(el("div", "zr-day", "Today")); st.log.appendChild(el("div", "zr-notice", NOTICE));
    var greetText = cfg.greeting || "Hi, I am Ziira. Ask me about our plans, what Ziira does, or whether it fits your business.";
    st.chips = el("div", "zr-replies"); st.chips.setAttribute("aria-label", "Suggested questions");
    function showGreeting() {
      var g = bubble("ziira"); g.parentNode.classList.add(auto ? "zr-in" : "zr-static"); g.appendChild(el("p", null, greetText)); stamp(g);
      st.log.appendChild(st.chips);
      st.msgs.forEach(function (m) {
        var b = bubble(m.role === "user" ? "user" : "ziira"); b.parentNode.classList.add("zr-static"); b._at = m.at;
        if (m.role === "user") { b.appendChild(el("p", null, m.text)); stamp(b, m.at, "read"); } else { addText(b, m.text, true); if (m.links) linkCards(b, m.links); }
      });
      // quick replies, or (limited mode) plain links to the key pages: nothing is answered here, only pointed to
      if (limited) enterLimited(true);
      else {
        var chips = (Array.isArray(cfg.suggestions) && cfg.suggestions.length ? cfg.suggestions : DEFAULT_CHIPS).slice(0, 5);
        chips.forEach(function (q) { var b = el("button", "zr-chip", String(q)); b.type = "button"; b.addEventListener("click", function () { send(String(q)); }); st.chips.appendChild(b); });
        st.chips.hidden = st.msgs.length > 0;
      }
      scroll();
    }
    if (auto) {
      st.chips.hidden = true;
      var wait = reduced ? 0 : 1100, dots = null;
      if (wait) { dots = el("div", "zr-typing"); var dd = el("span", "zr-dots"); dd.innerHTML = "<i></i><i></i><i></i>"; dots.appendChild(dd); st.log.appendChild(dots); setSub("typing…"); }
      st.timer = setTimeout(function () { if (!st) return; if (dots) dots.remove(); setSub("online"); showGreeting(); }, wait);
    } else showGreeting();
  }
  function newChat() {
    if (st.abort) st.abort.abort();
    clearTimeout(st.timer); st.cur = null; st.queue = []; st.playing = false; st.finished = false; st.msgs = []; save();
    setBusy(false); st.input.value = ""; seed(false); setSub("online"); autosize(); st.input.focus({ preventScroll: true });
  }

  function open(opts) {
    if (st) return;
    var root = build();
    st = { opts: opts, root: root, msgs: restore(), queue: [], busy: false, timer: 0, prevInert: [] };
    document.body.appendChild(root);
    st.dialog = root.querySelector(".zr-dialog"); st.log = root.querySelector(".zr-log"); 
    st.input = root.querySelector("textarea"); st.count = root.querySelector(".zr-count"); st.send = root.querySelector(".zr-send");
    var tm = root.querySelector(".zr-time"); tm.textContent = clock(); st.clock = setInterval(function () { tm.textContent = clock(); }, 20000);
    st.cfg = opts.config || {};
    st.auto = opts.auto === true && !(window.matchMedia && matchMedia("(max-width: 520px)").matches); st.engaged = !st.auto;
    var auto = st.auto;
    seed(auto);
    setBusy(false); autosize();

    var menu = root.querySelector(".zr-menu"), kebab = root.querySelector(".zr-kebab");
    function menuShow(on) { menu.hidden = !on; kebab.setAttribute("aria-expanded", on ? "true" : "false"); }
    kebab.addEventListener("click", function (e) { e.stopPropagation(); menuShow(menu.hidden); if (!menu.hidden) menu.querySelector("button").focus(); });
    st.menuShow = menuShow;
    root.addEventListener("click", function (e) {
      if (e.target.closest("[data-new]")) { menuShow(false); return newChat(); }
      if (e.target.closest("[data-close]")) return close();
      if (!menu.hidden && !e.target.closest(".zr-menu")) menuShow(false);
      if (st.playing && e.target.closest(".zr-bubble")) st.skip = true;
    });
    st.send.addEventListener("click", function (e) { if (st.busy) { e.preventDefault(); stop(); } else if (!st.input.value.trim()) { e.preventDefault(); st.input.focus(); } });
    root.querySelector("form").addEventListener("submit", function (e) { e.preventDefault(); if (!st.busy) send(st.input.value); });
    st.input.addEventListener("input", autosize);
    st.input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!st.busy) send(st.input.value); } });
    root.addEventListener("keydown", onKey);

    if (auto) {
      // Opened by itself: the page behind stays usable (no overlay, no inert, no scroll lock), nothing is announced and focus is
      // not moved. The window becomes a normal dialog only when the visitor clicks, taps or tabs into it.
      root.classList.add("zr-passive"); st.dialog.setAttribute("aria-modal", "false"); st.log.setAttribute("aria-live", "off");
      var engage = function () { if (st && !st.engaged) { st.engaged = true; st.dialog.setAttribute("aria-modal", "true"); st.log.setAttribute("aria-live", "polite"); } };
      st.dialog.addEventListener("pointerdown", engage); st.dialog.addEventListener("focusin", engage);
    } else {
      // keep the page behind out of reach while the chat is open
      Array.prototype.forEach.call(document.body.children, function (n) { if (n !== root && n.tagName !== "SCRIPT" && !n.inert) { n.inert = true; st.prevInert.push(n); } });
      document.documentElement.classList.add("zr-open");
    }
    if (opts.fab) opts.fab.classList.add("zr-hide");
    requestAnimationFrame(function () { requestAnimationFrame(function () { root.classList.add("zr-show"); st.log.scrollTop = st.log.scrollHeight; if (!auto) st.input.focus({ preventScroll: true }); }); });
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
    if (back && (!s.auto || s.engaged)) back.focus({ preventScroll: true });
  }

  window.ZiiraChat = { open: open, close: close };
})();
