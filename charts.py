"""The chart MCP App — one dynamic ``ui://`` template.

The Connext platform renders an MCP App by doing ``resources/read`` on the
``ui://`` resource and delivering the tool's ``structuredContent`` to it over the
SEP-1865 JSON-RPC bridge (``postMessage``). So the chart is **not** rendered
server-side — this template's inline JavaScript implements the bridge
(``ui/initialize`` → ``ui/notifications/initialized`` → receive
``ui/notifications/tool-result``), reads the tool's ``structuredContent``, and
draws the SVG in the browser. One template serves both chart tools; it picks the
chart from the data shape (``counts`` -> roadmap bar, ``weeks`` -> adoption line).

Self-contained (inline CSS + JS, no external assets) so it renders under the MCP
App iframe's strict CSP, and theme-aware via the host's CSS-variable tokens
(``hostContext.styles.variables``) + the ``data-theme`` mode. The data colours
are a validated categorical pair (blue/aqua). The template is a raw string literal
so the JS braces are literal text, not Python format fields.
"""

from __future__ import annotations

TEMPLATE = r"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      :root { --c-blue: #2a78d6; --c-aqua: #1baf7a; }
      :root[data-theme="dark"] { --c-blue: #3987e5; --c-aqua: #199e70; }
      body { font-family: system-ui, sans-serif; margin: 0;
             color: var(--mcp-color-text, #1a1a1a); background: transparent; }
      .card { margin: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
              border: 1px solid var(--mcp-color-border, #e3e3e8);
              background: var(--mcp-color-surface, #ffffff); }
      h2 { font-size: 1.05rem; margin: 0; }
      .sub { font-size: .8rem; opacity: .6; margin: .15rem 0 .6rem; }
      .empty { opacity: .5; font-size: .85rem; padding: 1.25rem 0; }
      /* Robust responsive SVG: 100% width, height from the viewBox aspect. */
      svg { width: 100%; height: auto; display: block; }
      svg text { fill: var(--mcp-color-text, #1a1a1a); }
      .val { font-size: 11px; font-weight: 600; text-anchor: middle; }
      .cat { font-size: 10px; text-anchor: middle; opacity: .6; }
      .tick { font-size: 9px; text-anchor: end; opacity: .5; }
      .end { font-size: 10px; font-weight: 600; }
      .grid { stroke: var(--mcp-color-border, #ececf0); stroke-width: 1; opacity: .6; }
      .axis { stroke: var(--mcp-color-border, #d8d8de); stroke-width: 1; }
      .legend { display: flex; gap: 1rem; font-size: .78rem; opacity: .85; margin-top: .4rem; }
      .lg { display: inline-flex; align-items: center; gap: .35rem; }
      .lg i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2 id="title">Product Studio chart</h2>
      <div class="sub" id="sub">Loading…</div>
      <div id="chart"><div class="empty">Run a chart tool to populate this.</div></div>
      <div class="legend" id="legend" style="display:none"></div>
    </div>
    <script>
      (function () {
        var RPC = "2.0", INIT_ID = 1;
        var STAGES = ["idea", "discovery", "design", "build", "beta", "ga"];
        function post(m) { (window.parent || window).postMessage(m, "*"); }
        function esc(s) {
          return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }
        function el(id) { return document.getElementById(id); }
        function postSize() {
          var h = Math.ceil(document.documentElement.scrollHeight || document.body.scrollHeight || 0);
          if (h > 0) post({ jsonrpc: RPC, method: "ui/notifications/size-changed", params: { height: h } });
        }

        // --- roadmap bar (single series) ---
        function bar(counts) {
          var W = 560, H = 280, pl = 34, pr = 14, pt = 26, pb = 46;
          var pw = W - pl - pr, ph = H - pt - pb;
          var data = STAGES.map(function (s) { return [s, counts[s] || 0]; });
          var vmax = Math.max(1, Math.max.apply(null, data.map(function (d) { return d[1]; })));
          var n = data.length, slot = pw / n, bw = slot * 0.56, base = pt + ph, out = "";
          out += '<line x1="' + pl + '" y1="' + base + '" x2="' + (W - pr) + '" y2="' + base + '" class="axis"/>';
          for (var i = 0; i < n; i++) {
            var stage = data[i][0], c = data[i][1];
            var x = pl + i * slot + (slot - bw) / 2, bh = (c / vmax) * ph, y = base - bh;
            out += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
                   '" height="' + Math.max(bh, 0.5).toFixed(1) + '" rx="4" fill="var(--c-blue)"/>';
            if (c) out += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 6).toFixed(1) + '" class="val">' + c + '</text>';
            out += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (base + 16).toFixed(1) + '" class="cat">' + esc(stage) + '</text>';
          }
          return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Features by stage">' + out + '</svg>';
        }

        // --- adoption + retention line (two series) ---
        function line(weeks, adoption, retention) {
          var W = 560, H = 280, pl = 36, pr = 74, pt = 22, pb = 34;
          var pw = W - pl - pr, ph = H - pt - pb, n = Math.max(weeks.length, 1);
          function X(i) { return pl + pw * i / Math.max(n - 1, 1); }
          function Y(v) { return pt + ph - v * ph; }
          var out = "";
          [0, 0.25, 0.5, 0.75, 1].forEach(function (g) {
            var gy = Y(g);
            out += '<line x1="' + pl + '" y1="' + gy.toFixed(1) + '" x2="' + (pl + pw).toFixed(1) + '" y2="' + gy.toFixed(1) + '" class="grid"/>';
            out += '<text x="' + (pl - 6) + '" y="' + (gy + 3).toFixed(1) + '" class="tick">' + Math.round(g * 100) + '%</text>';
          });
          function series(vals, v) {
            var pts = vals.map(function (val, i) { return X(i).toFixed(1) + "," + Y(val).toFixed(1); }).join(" ");
            var dots = vals.map(function (val, i) {
              return '<circle cx="' + X(i).toFixed(1) + '" cy="' + Y(val).toFixed(1) + '" r="2.5" fill="var(' + v + ')"/>';
            }).join("");
            return '<polyline points="' + pts + '" fill="none" stroke="var(' + v + ')" stroke-width="2"/>' + dots;
          }
          out += series(adoption, "--c-blue") + series(retention, "--c-aqua");
          if (n) {
            out += '<text x="' + (X(n - 1) + 8).toFixed(1) + '" y="' + (Y(adoption[n - 1]) + 3).toFixed(1) + '" class="end" style="fill:var(--c-blue)">Adoption</text>';
            out += '<text x="' + (X(n - 1) + 8).toFixed(1) + '" y="' + (Y(retention[n - 1]) + 3).toFixed(1) + '" class="end" style="fill:var(--c-aqua)">Retention</text>';
          }
          return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Adoption and retention over time">' + out + '</svg>';
        }

        function render(sc) {
          var chart = el("chart"), sub = el("sub"), title = el("title"), legend = el("legend");
          if (sc && sc.counts) {
            var total = 0; for (var k in sc.counts) total += sc.counts[k];
            title.textContent = "Roadmap by stage";
            sub.textContent = total + " " + (sc.scope || "features");
            chart.innerHTML = bar(sc.counts); legend.style.display = "none";
          } else if (sc && sc.weeks && sc.weeks.length) {
            title.textContent = (sc.feature || "Feature") + ": adoption & retention";
            sub.textContent = sc.weeks.length + " weeks";
            chart.innerHTML = line(sc.weeks, sc.adoption || [], sc.retention || []);
            legend.innerHTML = '<span class="lg"><i style="background:var(--c-blue)"></i>Adoption</span>' +
                               '<span class="lg"><i style="background:var(--c-aqua)"></i>Retention</span>';
            legend.style.display = "flex";
          } else {
            sub.textContent = "";
            chart.innerHTML = '<div class="empty">No chart data for this request.</div>';
            legend.style.display = "none";
          }
          if (window.requestAnimationFrame) window.requestAnimationFrame(postSize); else postSize();
        }

        function applyTheme(hc) {
          if (!hc) return;
          var root = document.documentElement;
          if (hc.theme) root.setAttribute("data-theme", hc.theme);
          var vars = (hc.styles && hc.styles.variables) || {};
          for (var name in vars) { if (vars[name] != null) root.style.setProperty(name, vars[name]); }
        }

        window.addEventListener("message", function (ev) {
          if (ev.source !== window.parent) return;
          var m = ev.data; if (!m || m.jsonrpc !== RPC) return;
          if (m.id === INIT_ID && m.result) {
            applyTheme(m.result.hostContext);
            post({ jsonrpc: RPC, method: "ui/notifications/initialized" });
          } else if (m.method === "ui/notifications/tool-result") {
            render(m.params && m.params.structuredContent);
          } else if (m.method === "ui/notifications/host-context-changed") {
            applyTheme(m.params);
          }
        });

        // Report content height so the host sizes the iframe to fit (no scroll).
        // ResizeObserver catches the chart render + any reflow (theme/font/width).
        if (window.ResizeObserver) new window.ResizeObserver(postSize).observe(document.body);
        postSize();
        post({ jsonrpc: RPC, id: INIT_ID, method: "ui/initialize",
               params: { protocolVersion: "2026-01-26", appCapabilities: {} } });
      })();
    </script>
  </body>
</html>"""


def template_html() -> str:
    """The chart MCP App template (the ``ui://`` resource Connext renders)."""
    return TEMPLATE
