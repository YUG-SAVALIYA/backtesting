"""
Redesign index.html → sidebar layout.
Reads ORIGINAL source, extracts content between reliable markers, writes new file.
"""
from pathlib import Path

# Read original source
orig_path = Path("static/index_original.html")
new_path  = Path("static/index.html")

# Make backup of original on first run
if not orig_path.exists():
    import shutil
    shutil.copy(new_path, orig_path)
    print("Backed up original to index_original.html")

src = orig_path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)
print(f"Original: {len(lines)} lines")

# ── Find reliable boundary markers ──────────────────────────────────────────
def find_line(needle):
    for i, l in enumerate(lines):
        if needle in l:
            return i
    raise ValueError(f"Marker not found: {needle!r}")

bt_open    = find_line('id="backtestView"')       # e.g. line 350 (0-indexed)
lv_open    = find_line('id="liveView"')            # e.g. line 710
scan_open  = find_line('<!-- SCANNER SECTION -->')  # e.g. line 795
modal_open = find_line('<!-- Stock Detail Modal -->')  # e.g. line 977
script_end = max(i for i,l in enumerate(lines) if '</script>' in l)

print(f"backtestView @ line {bt_open+1}")
print(f"liveView     @ line {lv_open+1}")
print(f"scanner      @ line {scan_open+1}")
print(f"modal        @ line {modal_open+1}")
print(f"script end   @ line {script_end+1}")

# ── Extract content slices ───────────────────────────────────────────────────
# Backtester: from backtestView div to just before liveView
backtester_content = "".join(lines[bt_open : lv_open - 1])

# Data collection: from liveView to just before scanner section
# Remove the inline display:none from liveView opening tag
liveview_lines = list(lines[lv_open : scan_open])
# Fix the outer liveView wrapper: remove display:none and remove max-width
for i, l in enumerate(liveview_lines):
    if 'id="liveView"' in l:
        liveview_lines[i] = l.replace('style="display: none;"', '').replace('style="display:none"', '')
        break
livedc_content = "".join(liveview_lines)

# Scanner: from <!-- SCANNER SECTION --> to just before modal
scanner_content = "".join(lines[scan_open : modal_open - 1])

# Modal + script: from modal to end of script
modal_and_script = "".join(lines[modal_open : script_end + 1])

print(f"Backtester content: {len(backtester_content)} chars")
print(f"Data collection:    {len(livedc_content)} chars")
print(f"Scanner content:    {len(scanner_content)} chars")
print(f"Modal+script:       {len(modal_and_script)} chars")

# ── Verify key elements ──────────────────────────────────────────────────────
assert "backtestForm"    in backtester_content, "backtestForm missing!"
assert "liveStatusBadge" in livedc_content,     "liveStatusBadge missing!"
assert "liveScannerPanel" in scanner_content,    "liveScannerPanel missing!"
assert "stockDetailOverlay" in modal_and_script, "modal missing!"
print("All key elements verified ✓")

# ── CSS ──────────────────────────────────────────────────────────────────────
CSS = """\
        :root{--bg-color:#0d1117;--panel-bg:#161b22;--border:#30363d;--text-main:#c9d1d9;--text-muted:#8b949e;--primary:#2f81f7;--primary-hover:#1f6feb;--success:#2ea043;--danger:#da3633;}
        *{box-sizing:border-box;}
        html,body{height:100%;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:0;}
        /* ── CRITICAL: inner containers must always be visible inside module panes ── */
        #module-backtester #backtestView { display:grid  !important; }
        #module-datacollect #liveView    { display:block !important; }
        /* Full layout */
        #appShell{display:flex;height:100vh;width:100vw;overflow:hidden;}
        /* SIDEBAR */
        #sidebar{width:220px;min-width:220px;background:#0d1117;border-right:1px solid #21262d;display:flex;flex-direction:column;transition:width .22s,min-width .22s;z-index:100;flex-shrink:0;}
        #sidebar.collapsed{width:60px;min-width:60px;}
        #sidebarHeader{display:flex;align-items:center;justify-content:space-between;padding:1rem .85rem;border-bottom:1px solid #21262d;min-height:60px;}
        #sidebarLogo{display:flex;align-items:center;gap:.6rem;overflow:hidden;white-space:nowrap;}
        .logo-icon{width:32px;height:32px;background:linear-gradient(135deg,#2f81f7,#ab71f8);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0;box-shadow:0 0 12px rgba(47,129,247,.35);}
        .logo-text{font-size:.78rem;font-weight:700;color:#fff;line-height:1.3;opacity:1;transition:opacity .15s;}
        #sidebar.collapsed .logo-text{opacity:0;width:0;overflow:hidden;}
        #sidebarToggle{background:transparent;border:none;color:#8b949e;cursor:pointer;padding:.3rem;border-radius:6px;display:flex;align-items:center;width:auto;margin:0;flex-shrink:0;transition:background .15s,color .15s;}
        #sidebarToggle:hover{background:rgba(255,255,255,.07);color:#fff;}
        #sidebarNav{list-style:none;padding:.75rem 0;flex:1;overflow-y:auto;margin:0;}
        #sidebarNav li{display:flex;align-items:center;gap:.75rem;padding:.7rem .9rem;margin:.15rem .5rem;border-radius:8px;cursor:pointer;transition:background .15s,color .15s;white-space:nowrap;overflow:hidden;color:#8b949e;font-size:.88rem;font-weight:500;border-left:3px solid transparent;}
        #sidebarNav li:hover{background:rgba(255,255,255,.06);color:#c9d1d9;}
        #sidebarNav li.active{background:rgba(47,129,247,.12);color:#58a6ff;border-left-color:#2f81f7;}
        #sidebarNav li.disabled{opacity:.38;cursor:not-allowed;pointer-events:none;}
        .nav-icon{font-size:1.1rem;flex-shrink:0;width:20px;text-align:center;}
        .nav-label{opacity:1;transition:opacity .15s;font-size:.85rem;}
        #sidebar.collapsed .nav-label{opacity:0;width:0;overflow:hidden;}
        .nav-badge{margin-left:auto;font-size:.6rem;background:rgba(255,255,255,.08);color:#8b949e;padding:.1rem .35rem;border-radius:20px;flex-shrink:0;}
        #sidebar.collapsed .nav-badge{display:none;}
        #sidebarFooter{padding:.6rem .9rem;border-top:1px solid #21262d;font-size:.68rem;color:#4a4f56;white-space:nowrap;overflow:hidden;}
        /* MAIN */
        #mainContent{flex:1;display:flex;flex-direction:column;overflow:hidden;}
        #topBar{height:48px;min-height:48px;background:#0d1117;border-bottom:1px solid #21262d;display:flex;align-items:center;padding:0 1.5rem;gap:.5rem;}
        #topBarTitle{font-size:.9rem;font-weight:700;color:#fff;}
        #topBarSubtitle{font-size:.72rem;color:#4a4f56;}
        #topBarRight{margin-left:auto;display:flex;align-items:center;gap:.5rem;font-size:.72rem;color:#4a4f56;}
        #moduleArea{flex:1;overflow-y:auto;overflow-x:hidden;}
        .module-pane{display:none;padding:1.5rem;min-height:100%;}
        .module-pane.active{display:block;}
        #module-datacollect{padding:0;}
        #module-datacollect.active{display:flex;flex-direction:column;}
        #module-portfolio.active{display:flex;align-items:center;justify-content:center;padding:3rem;}
        /* EXISTING INNER STYLES (preserved) */
        .container{width:100%;display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;}
        .panel{background:var(--panel-bg);border:1px solid var(--border);border-radius:8px;padding:1.5rem;box-shadow:0 4px 12px rgba(0,0,0,.15);}
        .full-width{grid-column:1/-1;}
        .form-group{margin-bottom:1.25rem;}
        .form-group label{display:block;margin-bottom:.5rem;font-weight:500;font-size:.9rem;}
        .form-control{width:100%;background:#0d1117;border:1px solid var(--border);color:var(--text-main);padding:.5rem .75rem;border-radius:6px;font-size:.95rem;transition:border-color .2s;}
        .form-control:focus{outline:none;border-color:var(--primary);}
        .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:1rem;}
        button{width:100%;background:var(--success);color:#fff;border:none;padding:.75rem;font-size:1rem;font-weight:600;border-radius:6px;cursor:pointer;transition:background-color .2s;margin-top:1rem;}
        button:hover{background:#238636;}
        button:disabled{background:var(--border);cursor:not-allowed;color:var(--text-muted);}
        .toggle-btn{background:transparent;border:1px solid var(--primary);color:var(--primary);padding:.35rem .75rem;font-size:.8rem;margin:0;width:auto;}
        .toggle-btn:hover{background:rgba(88,166,255,.1);}
        .results{margin-top:2rem;display:none;}
        .metrics-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem;margin-bottom:2rem;}
        .metric-card{background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:1rem;text-align:center;}
        .metric-value{font-size:1.5rem;font-weight:700;color:var(--primary);margin-top:.5rem;}
        table{width:100%;border-collapse:collapse;font-size:.9rem;}
        th,td{padding:.75rem;text-align:left;border-bottom:1px solid var(--border);}
        th{font-weight:600;color:var(--text-muted);background:rgba(255,255,255,.02);}
        .status-win{color:var(--success);}.status-loss{color:var(--danger);}.status-expired{color:var(--text-muted);}
        .loader{display:none;border:3px solid rgba(255,255,255,.1);border-radius:50%;border-top:3px solid var(--primary);width:24px;height:24px;animation:spin 1s linear infinite;margin:0 auto;}
        @keyframes spin{0%{transform:rotate(0deg);}100%{transform:rotate(360deg);}}
        @keyframes slideUp{from{opacity:0;transform:translateY(24px);}to{opacity:1;transform:translateY(0);}}
        @keyframes pulse{0%,100%{box-shadow:0 0 8px rgba(22,163,74,.5);}50%{box-shadow:0 0 20px rgba(22,163,74,.9);}}
        @keyframes shimmer{0%{background-position:0% 0%;}100%{background-position:200% 0%;}}
        #liveScannerPanel{background:linear-gradient(135deg,rgba(22,27,34,.95),rgba(13,17,23,.98));border:1px solid rgba(47,129,247,.18);border-radius:16px;padding:1.75rem;box-shadow:0 8px 32px rgba(0,0,0,.4);position:relative;overflow:hidden;}
        #liveScannerPanel::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#2f81f7,#58a6ff,#ab71f8,#2f81f7);background-size:200% 100%;animation:shimmer 3s linear infinite;}
        .scanner-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:1px solid rgba(255,255,255,.06);}
        .scanner-title{margin:0;font-size:1.15rem;font-weight:700;color:#fff;display:flex;align-items:center;gap:.6rem;}
        #btnRunScan{background:linear-gradient(135deg,#2f81f7,#1f6feb) !important;box-shadow:0 0 16px rgba(47,129,247,.4),0 4px 12px rgba(0,0,0,.3);border-radius:8px !important;font-weight:700 !important;transition:box-shadow .2s,transform .15s;padding:.55rem 1.6rem !important;}
        #btnRunScan:hover{box-shadow:0 0 24px rgba(47,129,247,.6);transform:translateY(-1px);}
        #liveScannerPanel input::-webkit-outer-spin-button,#liveScannerPanel input::-webkit-inner-spin-button{-webkit-appearance:none;margin:0;}
        #liveScannerPanel input[type=number]{-moz-appearance:textfield;}
        .scan-config-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.25rem;}
        .scan-param{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:.85rem;transition:border-color .2s,background .2s;}
        .scan-param:hover{border-color:rgba(47,129,247,.3);background:rgba(47,129,247,.04);}
        .scan-param label{display:block;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin-bottom:.55rem;}
        .scan-param .form-control{background:rgba(0,0,0,.3);border-color:rgba(255,255,255,.1);}
        .scan-param .form-control:focus{border-color:#2f81f7;box-shadow:0 0 0 2px rgba(47,129,247,.15);}
        .live-filter-bar{background:rgba(47,129,247,.06);border:1px solid rgba(47,129,247,.2);border-radius:10px;padding:.9rem 1.1rem;margin-bottom:1.25rem;}
        .scan-results-table th{background:rgba(255,255,255,.025);font-size:.73rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;padding:.75rem .9rem;color:var(--text-muted);white-space:nowrap;border-bottom:1px solid rgba(255,255,255,.08);}
        .scan-results-table td{padding:.7rem .9rem;border-bottom:1px solid rgba(255,255,255,.05);}
        .scan-results-table tr:last-child td{border-bottom:none;}
        .scan-results-table tr:hover td{background:rgba(47,129,247,.05);}
        .badge-up{color:#2ea043;font-weight:700;font-size:.75rem;}
        .badge-down{color:#da3633;font-weight:700;font-size:.75rem;}
        .badge-above{background:rgba(46,160,67,.15);color:#2ea043;padding:.15rem .45rem;border-radius:20px;font-size:.72rem;font-weight:600;}
        .badge-below{background:rgba(218,54,51,.15);color:#da3633;padding:.15rem .45rem;border-radius:20px;font-size:.72rem;font-weight:600;}
        .detail-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem;padding:1.25rem;}
        .detail-card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:.9rem 1rem;}
        .detail-card .dc-label{font-size:.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:.3rem;}
        .detail-card .dc-value{font-size:1.1rem;font-weight:700;}
        #stockDetailModal::-webkit-scrollbar{width:5px;}
        #stockDetailModal::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:4px;}
        @media(max-width:520px){.detail-grid{grid-template-columns:1fr 1fr;}}
"""

SIDEBAR_JS = """\
    <script>
    /* ── Module Navigation ─────────────────────────────────────── */
    const MODULE_META = {
        scanner:     {title:'Signal Scanner',      subtitle:'Live market scanning \xb7 RSI + Supertrend'},
        backtester:  {title:'Strategy Backtester', subtitle:'Historical signal backtesting'},
        datacollect: {title:'Data Collection',     subtitle:'Live trading data pipeline'},
        portfolio:   {title:'Live Portfolio',      subtitle:'Coming soon'},
    };
    function switchModule(name) {
        document.querySelectorAll('.module-pane').forEach(p => p.classList.remove('active'));
        const pane = document.getElementById('module-' + name);
        if (pane) pane.classList.add('active');
        document.querySelectorAll('#sidebarNav li').forEach(li =>
            li.classList.toggle('active', li.dataset.module === name));
        const m = MODULE_META[name] || {};
        const t = document.getElementById('topBarTitle');
        const s = document.getElementById('topBarSubtitle');
        if (t) t.textContent = m.title    || name;
        if (s) s.textContent = m.subtitle || '';
    }
    function toggleSidebar() {
        document.getElementById('sidebar').classList.toggle('collapsed');
    }
    /* Override old switchMainTab — route to new system, never touch inner divs */
    function switchMainTab(tab) {
        if (tab === 'backtest') switchModule('backtester');
        else if (tab === 'live') switchModule('scanner');
    }
    function updateClock() {
        const el = document.getElementById('topBarClock');
        if (el) el.textContent = new Date().toLocaleTimeString('en-IN',
            {hour:'2-digit',minute:'2-digit',second:'2-digit'});
    }
    setInterval(updateClock,1000); updateClock();
    </script>
"""

# ── Write output ─────────────────────────────────────────────────────────────
with new_path.open("w", encoding="utf-8") as f:
    f.write("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n")
    f.write("    <meta charset=\"UTF-8\">\n")
    f.write("    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n")
    f.write("    <title>RSI Supertrend \u2014 Trading Suite</title>\n")
    f.write("    <style>\n")
    f.write(CSS)
    f.write("    </style>\n")
    # Early override of switchMainTab BEFORE main script runs
    f.write("    <script>\n")
    f.write("    // Early override — prevents old init code from hiding inner containers\n")
    f.write("    function switchMainTab(tab){} // will be properly defined after load\n")
    f.write("    </script>\n")
    f.write("</head>\n<body>\n<div id=\"appShell\">\n\n")

    # Sidebar
    f.write("""<!-- SIDEBAR -->
<nav id="sidebar">
    <div id="sidebarHeader">
        <div id="sidebarLogo">
            <div class="logo-icon">\U0001f4c8</div>
            <div class="logo-text">RSI<br>Supertrend</div>
        </div>
        <button id="sidebarToggle" onclick="toggleSidebar()" title="Toggle sidebar" style="background:transparent;border:none;color:#8b949e;cursor:pointer;padding:.3rem;border-radius:6px;display:flex;align-items:center;width:auto;margin:0;flex-shrink:0;">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="3" y1="6"  x2="21" y2="6"/>
                <line x1="3" y1="12" x2="21" y2="12"/>
                <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
        </button>
    </div>
    <ul id="sidebarNav">
        <li data-module="scanner" class="active" onclick="switchModule('scanner')" title="Signal Scanner">
            <span class="nav-icon">\U0001f52d</span><span class="nav-label">Scanner</span>
        </li>
        <li data-module="backtester" onclick="switchModule('backtester')" title="Strategy Backtester">
            <span class="nav-icon">\U0001f4ca</span><span class="nav-label">Backtester</span>
        </li>
        <li data-module="datacollect" onclick="switchModule('datacollect')" title="Data Collection">
            <span class="nav-icon">\U0001f4e1</span><span class="nav-label">Data Collection</span>
        </li>
        <li data-module="portfolio" class="disabled" title="Coming Soon">
            <span class="nav-icon">\U0001f4bc</span><span class="nav-label">Live Portfolio</span>
            <span class="nav-badge">Soon</span>
        </li>
    </ul>
    <div id="sidebarFooter">v2.0 \xb7 NSE Equity</div>
</nav>

<!-- MAIN -->
<main id="mainContent">
    <div id="topBar">
        <span id="topBarTitle">Signal Scanner</span>
        <span id="topBarSubtitle">Live market scanning \xb7 RSI + Supertrend</span>
        <div id="topBarRight">
            <span id="topBarClock" style="font-variant-numeric:tabular-nums;"></span>
            <span style="color:#21262d;">|</span>
            <span>IST</span>
        </div>
    </div>
    <div id="moduleArea">

        <!-- MODULE: SCANNER -->
        <div id="module-scanner" class="module-pane active">
""")

    f.write(scanner_content)

    f.write("""
        </div><!-- /module-scanner -->

        <!-- MODULE: BACKTESTER -->
        <div id="module-backtester" class="module-pane">
""")

    f.write(backtester_content)

    f.write("""
        </div><!-- /module-backtester -->

        <!-- MODULE: DATA COLLECTION (live trading pipeline) -->
        <div id="module-datacollect" class="module-pane">
""")

    f.write(livedc_content)

    f.write("""
        </div><!-- /module-datacollect -->

        <!-- MODULE: LIVE PORTFOLIO -->
        <div id="module-portfolio" class="module-pane">
            <div style="text-align:center;max-width:420px;">
                <div style="font-size:5rem;margin-bottom:1.5rem;">\U0001f4bc</div>
                <h2 style="color:#fff;font-size:1.8rem;margin-bottom:.75rem;">Live Portfolio</h2>
                <p style="color:#8b949e;font-size:1rem;line-height:1.6;margin-bottom:2rem;">
                    Real-time portfolio tracking, P&amp;L monitoring, and position management.
                    <strong style="color:#4a4f56;"> Coming soon.</strong>
                </p>
                <div style="display:inline-flex;align-items:center;gap:.5rem;background:rgba(255,202,40,.08);border:1px solid rgba(255,202,40,.25);padding:.5rem 1.2rem;border-radius:20px;color:#ffca28;font-size:.82rem;font-weight:600;">
                    \U0001f6a7 Under Development
                </div>
            </div>
        </div><!-- /module-portfolio -->

    </div><!-- /moduleArea -->
</main>
</div><!-- /appShell -->

""")

    # Modal + original script block
    f.write(modal_and_script)

    # Sidebar JS (final override after main script)
    f.write("\n")
    f.write(SIDEBAR_JS)
    f.write("\n</body>\n</html>\n")

result = new_path.read_text(encoding="utf-8")
print(f"\nOutput: {len(result)} chars, {result.count(chr(10))} lines")
checks = {
    "backtestView"    : "backtestView"     in result,
    "backtestForm"    : "backtestForm"     in result,
    "liveView"        : "liveView"         in result,
    "liveStatusBadge" : "liveStatusBadge"  in result,
    "liveScannerPanel": "liveScannerPanel" in result,
    "applyScanFilters": "applyScanFilters" in result,
    "module-backtester":"module-backtester"in result,
    "module-datacollect":"module-datacollect" in result,
    "switchModule"    : "switchModule"     in result,
}
for k,v in checks.items():
    print(f"  {'OK' if v else 'MISSING'} {k}")
