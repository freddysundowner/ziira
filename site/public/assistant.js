/* Ask Ziira launcher (about 3 KB). Adds the round button on every page it is included in: it is always there. It never reads the
   API to decide that. The chat (assistant-chat.js, assistant.css) loads when the browser is idle or on the first click, and the chat
   itself finds out whether the API can answer; if not, it opens in a calm "limited mode" with plain links. "Ask Ziira" links on the
   page open the chat too (and are ordinary links to /ai/ until this script runs). */
(function () {
  var me = document.currentScript;
  if (!me || !me.dataset.api) return;
  var d = me.dataset, api = d.api.replace(/\/+$/, ""), base = me.src.replace(/[^/]*$/, ""), KEY = "zr-assistant-config", cfg = null, cfgWait = null, btn = null, chat = null;

  // Asked once per page view (and cached for the session only when the assistant could answer). Any failure means "limited mode".
  function getConfig(done) {
    if (cfg) return done(cfg);
    if (cfgWait) { cfgWait.push(done); return; }
    cfgWait = [done];
    function end(o) { cfg = o; var q = cfgWait; cfgWait = null; q.forEach(function (f) { f(o); }); }
    try { var c = JSON.parse(sessionStorage.getItem(KEY) || "null"); if (c && c.enabled === true) return end(c); } catch (e) {}
    var ctl = typeof AbortController === "function" ? new AbortController() : null, t = ctl && setTimeout(function () { ctl.abort(); }, 4000);
    fetch(api + "/api/v1/public/assistant/config", { credentials: "omit", signal: ctl ? ctl.signal : undefined })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        var o = j && typeof j === "object" ? j : { enabled: false };
        if (o.enabled === true) { try { sessionStorage.setItem(KEY, JSON.stringify(o)); } catch (e) {} }
        end(o);
      })
      .catch(function () { end({ enabled: false }); })
      .then(function () { if (t) clearTimeout(t); });
  }

  function loadChat(then) {
    if (window.ZiiraChat) return then();
    if (chat) { chat.push(then); return; }
    chat = [then];
    var s = document.createElement("script");
    s.src = base + "assistant-chat.js"; s.async = true;
    s.onload = function () { var q = chat; chat = null; q.forEach(function (f) { f(); }); };
    s.onerror = function () { chat = null; if (btn) btn.removeAttribute("aria-busy"); };
    document.head.appendChild(s);
  }

  function open(from, auto) {
    seen();
    if (btn) btn.setAttribute("aria-busy", "true");
    loadChat(function () {
      getConfig(function (c) {
        if (btn) btn.removeAttribute("aria-busy");
        window.ZiiraChat.open({ api: api, config: c, pricing: d.pricing, contact: d.contact, who: d.who, security: d.security, opener: from || btn, fab: btn, auto: auto === true });
      });
    });
  }


  /* ---- the invitation: on the main pages the phone-style window opens by itself once per browser session (tablet, desktop);
     on phone widths, where the chat is a full-screen sheet, only a small greeting bubble above the button appears (never a sheet) ---- */
  var SEEN = "zr-assistant-seen", NARROW = "(max-width: 520px)";
  var PAGES = /^(?:\/|\/ai\/?|\/pricing\/?|\/solutions\/.*)$/;
  function autoMode(path, narrow, alreadySeen) {
    if (alreadySeen || !PAGES.test(path)) return "none";
    return narrow ? "nudge" : "window";
  }
  function isSeen() { try { return !!sessionStorage.getItem(SEEN); } catch (e) { return false; } }
  function seen() { try { sessionStorage.setItem(SEEN, "1"); } catch (e) {} }
  window.ZiiraLauncher = { autoMode: autoMode };

  function nudge() {
    var n = document.createElement("button");
    n.type = "button"; n.className = "zr-nudge"; n.setAttribute("aria-hidden", "true"); n.tabIndex = -1; n.textContent = "Hi, ask me anything about Ziira";
    document.body.appendChild(n);
    requestAnimationFrame(function () { n.classList.add("zr-in"); });
    var gone = false, t = setTimeout(function () { dismiss(); }, 8000);
    function dismiss() { if (gone) return; gone = true; clearTimeout(t); window.removeEventListener("scroll", dismiss); n.classList.remove("zr-in"); setTimeout(function () { n.remove(); }, 250); }
    window.addEventListener("scroll", dismiss, { passive: true, once: true });
    n.addEventListener("click", function () { dismiss(); open(btn); });
    btn.addEventListener("click", dismiss);
  }

  function invite() {
    var mode = autoMode(location.pathname, window.matchMedia && matchMedia(NARROW).matches, isSeen());
    if (mode === "none") return;
    setTimeout(function () {
      if (isSeen() || !btn || window.ZiiraChat && document.querySelector(".zr-root")) return;
      seen();
      if (mode === "nudge") nudge(); else open(btn, true);
    }, Math.max(0, 2500 - (window.performance ? performance.now() : 0)));
  }

  function start() {
    var link = document.createElement("link");
    link.rel = "stylesheet"; link.href = base + "assistant.css";
    link.onload = function () {
      btn = document.createElement("button");
      btn.type = "button"; btn.className = "zr-fab"; btn.setAttribute("aria-haspopup", "dialog"); btn.setAttribute("aria-label", "Ask Ziira");
      btn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" fill="currentColor"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" fill="currentColor"/></svg><span>Ask Ziira</span>';
      btn.addEventListener("click", function () { open(btn); });
      document.body.appendChild(btn);
      requestAnimationFrame(function () { btn.classList.add("zr-in"); });
      invite();
      (window.requestIdleCallback || function (f) { setTimeout(f, 2500); })(function () { loadChat(function () {}); getConfig(function () {}); });
    };
    link.onerror = function () {};
    document.head.appendChild(link);
    // Any "Ask Ziira anything" link or button on the page opens the assistant (it is an ordinary link to /ai/ until then).
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("[data-ask-ziira]");
      if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      e.preventDefault(); open(a);
    });
  }

  function init() { start(); }
  if (document.readyState === "complete") (window.requestIdleCallback || setTimeout)(init);
  else window.addEventListener("load", function () { (window.requestIdleCallback || setTimeout)(init); });
})();
