"""The feedback-form MCP App — a WRITABLE ``ui://`` template (SEP-1865).

Unlike the read-only chart app, this one WRITES: the form's JS calls the
``log_feedback`` tool back on the server over the host ``tools/call`` bridge
(gated by the admin's ``app_callable`` allowlist), the server persists the note
to SQLite, and the app re-renders the "Recent" list from the tool result — the
full form -> persist -> read-back loop, driven entirely from the Connext side.

Data flow:
  * ``feedback_form`` tool  -> initial ``structuredContent`` {features, recent}
    delivered via ``ui/notifications/tool-result`` -> render dropdown + list.
  * on Save -> ``tools/call`` log_feedback {feature, sentiment, note} -> the
    tool INSERTs and returns updated ``structuredContent`` {recent} -> re-render.

Self-contained inline CSS + JS (strict MCP-App CSP), theme-aware, and it reports
its height via ``ui/notifications/size-changed`` so the host fits the iframe. The
template is a raw string literal so the JS braces are literal text.
"""

from __future__ import annotations

TEMPLATE = r"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      :root { --accent: #2a78d6; --ok: #1baf7a; --err: #d64550; }
      :root[data-theme="dark"] { --accent: #3987e5; --ok: #199e70; --err: #e5687a; }
      body { font-family: system-ui, sans-serif; margin: 0;
             color: var(--mcp-color-text, #1a1a1a); background: transparent; }
      .card { margin: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
              border: 1px solid var(--mcp-color-border, #e3e3e8);
              background: var(--mcp-color-surface, #ffffff); }
      h2 { font-size: 1.05rem; margin: 0; }
      .sub { font-size: .8rem; opacity: .6; margin: .15rem 0 .8rem; }
      .form { display: flex; flex-direction: column; gap: .6rem; }
      label.field { display: flex; flex-direction: column; gap: .25rem;
                    font-size: .78rem; opacity: .75; }
      select, textarea {
        font: inherit; font-size: .9rem; color: inherit;
        background: var(--mcp-color-surface, #fff);
        border: 1px solid var(--mcp-color-border, #d8d8de);
        border-radius: 8px; padding: .45rem .55rem; width: 100%; box-sizing: border-box;
      }
      textarea { resize: vertical; min-height: 2.4rem; }
      .moods { display: flex; gap: .5rem; flex-wrap: wrap; }
      .moods label { display: inline-flex; align-items: center; gap: .3rem;
                     font-size: .85rem; padding: .3rem .55rem; border-radius: 999px;
                     border: 1px solid var(--mcp-color-border, #d8d8de); cursor: pointer; }
      .moods input { accent-color: var(--accent); margin: 0; }
      .row { display: flex; align-items: center; gap: .75rem; }
      button { font: inherit; font-weight: 600; font-size: .85rem; color: #fff;
               background: var(--accent); border: 0; border-radius: 8px;
               padding: .5rem .9rem; cursor: pointer; }
      button:disabled { opacity: .55; cursor: default; }
      .status { font-size: .8rem; }
      .status.ok { color: var(--ok); font-weight: 600; }
      .status.err { color: var(--err); }
      .recent { margin-top: 1rem; border-top: 1px solid var(--mcp-color-border, #ececf0); padding-top: .6rem; }
      .rhead { font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; opacity: .55; margin-bottom: .35rem; }
      ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .4rem; }
      li { display: flex; gap: .5rem; font-size: .85rem; align-items: baseline; }
      li .mood { font-size: 1rem; line-height: 1; }
      li .by { opacity: .5; font-size: .75rem; }
      li.muted { opacity: .5; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Log customer feedback</h2>
      <div class="sub">Capture a note about a feature — it's saved in Product Studio.</div>
      <div class="form" id="form">
        <label class="field">Feature
          <select id="feature"></select>
        </label>
        <div class="field">Sentiment
          <div class="moods">
            <label><input type="radio" name="s" value="positive" checked> 🙂 Positive</label>
            <label><input type="radio" name="s" value="neutral"> 😐 Neutral</label>
            <label><input type="radio" name="s" value="negative"> 🙁 Negative</label>
          </div>
        </div>
        <label class="field">Note
          <textarea id="note" placeholder="What did the customer say?"></textarea>
        </label>
        <div class="row">
          <button type="button" id="save">Save feedback</button>
          <span class="status" id="status"></span>
        </div>
      </div>
      <div class="recent">
        <div class="rhead">Recent</div>
        <ul id="list"><li class="muted">Loading…</li></ul>
      </div>
    </div>
    <script>
      (function () {
        var RPC = "2.0", INIT_ID = 1, reqSeq = 100, pending = {};
        var MOODS = { positive: "🙂", neutral: "😐", negative: "🙁" };
        function post(m) { (window.parent || window).postMessage(m, "*"); }
        function el(id) { return document.getElementById(id); }
        function esc(s) {
          return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }
        function postSize() {
          var h = Math.ceil(document.documentElement.scrollHeight || document.body.scrollHeight || 0);
          if (h > 0) post({ jsonrpc: RPC, method: "ui/notifications/size-changed", params: { height: h } });
        }
        function reflow() { if (window.requestAnimationFrame) window.requestAnimationFrame(postSize); else postSize(); }

        // Call a tool back on the server over the host bridge (needs app_callable).
        function callTool(name, args) {
          return new Promise(function (resolve, reject) {
            var id = ++reqSeq;
            pending[id] = { resolve: resolve, reject: reject };
            post({ jsonrpc: RPC, id: id, method: "tools/call", params: { name: name, arguments: args } });
          });
        }

        function renderFeatures(features) {
          var sel = el("feature");
          if (!features || !features.length || sel.options.length) return;
          sel.innerHTML = features.map(function (t) { return '<option>' + esc(t) + '</option>'; }).join("");
        }
        function renderList(recent) {
          var ul = el("list");
          if (!recent || !recent.length) { ul.innerHTML = '<li class="muted">No feedback yet.</li>'; return; }
          ul.innerHTML = recent.map(function (f) {
            return '<li><span class="mood">' + (MOODS[f.sentiment] || "•") + '</span>' +
                   '<span><b>' + esc(f.feature) + '</b> — ' + esc(f.note) +
                   '<span class="by"> · ' + esc(f.submitted_by || f.by || "") + '</span></span></li>';
          }).join("");
        }
        function setStatus(msg, kind) { var s = el("status"); s.textContent = msg || ""; s.className = "status " + (kind || ""); }
        function toolErrText(result) {
          try { return (result.content || []).map(function (c) { return c.text; }).filter(Boolean).join(" "); }
          catch (e) { return "error"; }
        }

        function render(sc) {
          if (!sc) return;
          renderFeatures(sc.features);
          if (sc.recent) renderList(sc.recent);
          reflow();
        }

        function onSubmit(e) {
          e.preventDefault();
          var feature = el("feature").value;
          var moodEl = document.querySelector('input[name="s"]:checked');
          var sentiment = moodEl ? moodEl.value : "neutral";
          var note = el("note").value.trim();
          if (!feature) { setStatus("Pick a feature first.", "err"); return; }
          if (!note) { setStatus("Add a short note first.", "err"); return; }
          var btn = el("save"); btn.disabled = true; setStatus("Saving…", "");
          callTool("log_feedback", { feature: feature, sentiment: sentiment, note: note })
            .then(function (result) {
              btn.disabled = false;
              if (result && result.isError) { setStatus("Couldn't save — " + toolErrText(result), "err"); return; }
              var sc = result && (result.structuredContent || result.structured_content);
              if (sc && sc.recent) renderList(sc.recent);
              el("note").value = "";
              setStatus("Saved ✓", "ok");
              reflow();
            })
            .catch(function (err) {
              btn.disabled = false;
              setStatus(
                err && err.notPermitted
                  ? "This form isn't allowed to save yet — an admin must enable it (app-callable)."
                  : "Couldn't save — " + ((err && err.message) || "error"),
                "err"
              );
            });
        }

        function applyTheme(hc) {
          if (!hc) return;
          var root = document.documentElement;
          if (hc.theme) root.setAttribute("data-theme", hc.theme);
          var vars = (hc.styles && hc.styles.variables) || {};
          for (var n in vars) { if (vars[n] != null) root.style.setProperty(n, vars[n]); }
        }

        window.addEventListener("message", function (ev) {
          if (ev.source !== window.parent) return;
          var m = ev.data; if (!m || m.jsonrpc !== RPC) return;
          if (m.id === INIT_ID && m.result) {
            applyTheme(m.result.hostContext);
            post({ jsonrpc: RPC, method: "ui/notifications/initialized" });
          } else if (pending[m.id] && (("result" in m) || ("error" in m))) {
            var p = pending[m.id]; delete pending[m.id];
            if ("error" in m) {
              var e = new Error((m.error && m.error.message) || "tool error");
              e.notPermitted = m.error && m.error.code === -32001;
              p.reject(e);
            } else { p.resolve(m.result); }
          } else if (m.method === "ui/notifications/tool-result") {
            render(m.params && m.params.structuredContent);
          } else if (m.method === "ui/notifications/host-context-changed") {
            applyTheme(m.params);
          }
        });

        // A plain button + click handler — NOT a native <form> submit, which the
        // MCP App iframe (sandbox="allow-scripts", no allow-forms) would block.
        el("save").addEventListener("click", onSubmit);
        if (window.ResizeObserver) new window.ResizeObserver(postSize).observe(document.body);
        postSize();
        post({ jsonrpc: RPC, id: INIT_ID, method: "ui/initialize",
               params: { protocolVersion: "2026-01-26", appCapabilities: {} } });
      })();
    </script>
  </body>
</html>"""


def template_html() -> str:
    """The feedback-form MCP App template (the ``ui://`` resource Connext renders)."""
    return TEMPLATE
