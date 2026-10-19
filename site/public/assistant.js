/* Ask Ziira launcher (about 2 KB). Checks, once per session, whether the assistant is switched on; only then adds the round button.
   The chat itself (assistant-chat.js, assistant.css) loads on the first click or when the browser is idle. Without this file, or if the
   API is unreachable or the assistant is off, the page is unchanged: "Ask Ziira" links on the page just open the /ai/ page. */
(function () {
  var me = document.currentScript;
  if (!me || !me.dataset.api) return;
  var d = me.dataset, api = d.api.replace(/\/+$/, ""), base = me.src.replace(/[^/]*$/, ""), KEY = "zr-assistant-config", cfg = null, btn = null, chat = null;

  function getConfig(done) {
    try { var c = sessionStorage.getItem(KEY); if (c) return done(JSON.parse(c)); } catch (e) {}
    var ctl = typeof AbortController === "function" ? new AbortController() : null, t = ctl && setTimeout(function () { ctl.abort(); }, 6000);
    fetch(api + "/api/v1/public/assistant/config", { credentials: "omit", signal: ctl ? ctl.signal : undefined })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        var o = j && j.enabled === true ? j : { enabled: false };
        if (j) { try { sessionStorage.setItem(KEY, JSON.stringify(o)); } catch (e) {} }
        done(o);
      })
      .catch(function () { done({ enabled: false }); })
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

  function open(from) {
    if (btn) btn.setAttribute("aria-busy", "true");
    loadChat(function () {
      if (btn) btn.removeAttribute("aria-busy");
      window.ZiiraChat.open({ api: api, config: cfg, pricing: d.pricing, contact: d.contact, opener: from || btn, fab: btn });
    });
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
      (window.requestIdleCallback || function (f) { setTimeout(f, 2500); })(function () { loadChat(function () {}); });
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

  function init() { getConfig(function (c) { cfg = c; if (c.enabled) start(); }); }
  if (document.readyState === "complete") (window.requestIdleCallback || setTimeout)(init);
  else window.addEventListener("load", function () { (window.requestIdleCallback || setTimeout)(init); });
})();
