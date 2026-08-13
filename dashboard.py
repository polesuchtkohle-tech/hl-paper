"""Statisches HTML-Dashboard fuer den Paper-Trader.

Generiert eine einzelne HTML-Datei mit Plotly-Charts.

Aufruf: uv run python dashboard.py [--db-pfad paper.db] [--ausgabe dashboard.html]
"""

import argparse
import json
import math
import statistics
from datetime import datetime, timezone

from db import get_connection, get_konten, get_equity_history


def erstelle_dashboard(db_pfad: str = "paper.db", ausgabe: str = "dashboard.html") -> str:
    """Erstellt das HTML-Dashboard und gibt den Pfad zurueck."""
    conn = get_connection(db_pfad)
    alle_konten = get_konten(conn)

    breakout = [k for k in alle_konten if k["strategie"] == "breakout"]
    aktiv = [k for k in breakout if k["status"] == "aktiv"]
    ruiniert_konten = [k for k in breakout if k["status"] == "ruiniert"]
    bah = next((k for k in alle_konten if k["strategie"] == "buy_and_hold"), None)

    # Letzte Kerze
    letzte_kerze = conn.execute("SELECT MAX(zeit) FROM equity").fetchone()[0] or "—"

    # Trades gesamt + ambivalente Kerzen
    gesamt_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    gesamt_ambivalent = conn.execute("SELECT SUM(ambivalente_kerzen) FROM konten").fetchone()[0] or 0

    # Equity-Kurven der Top 10 (nach Kontostand sortiert)
    top10 = sorted(aktiv, key=lambda k: k["kontostand"], reverse=True)[:10]
    equity_traces = []
    hat_equity_daten = False
    for k in top10:
        history = get_equity_history(conn, k["konto_id"])
        if history:
            hat_equity_daten = True
            zeiten = [e["zeit"] for e in history]
            staende = [e["kontostand"] for e in history]
            equity_traces.append({
                "x": zeiten,
                "y": staende,
                "type": "scatter",
                "mode": "lines",
                "name": k["konto_id"][:20],
                "line": {"width": 2},
            })

    # Histogram: alle Breakout-Konten
    alle_staende = [k["kontostand"] for k in breakout]
    histogram_trace = {
        "x": alle_staende,
        "type": "histogram",
        "nbinsx": 30,
        "name": "Kontostand-Verteilung",
        "marker": {"color": "#7c85f5"},
    }

    # Ruinquote je Hebelstufe
    hebel_stufen = [1, 3, 5, 10, 25]
    ruinquoten = []
    hebel_labels = []
    for h in hebel_stufen:
        total = sum(1 for k in breakout if k["hebel"] == h)
        ruin = sum(1 for k in breakout if k["hebel"] == h and k["status"] == "ruiniert")
        pct = ruin / total * 100 if total > 0 else 0
        ruinquoten.append(round(pct, 1))
        hebel_labels.append(f"{h}x")

    ruin_trace = {
        "x": hebel_labels,
        "y": ruinquoten,
        "type": "bar",
        "name": "Ruinquote (%)",
        "marker": {"color": ["#4ade80" if q == 0 else "#f59e0b" if q < 50 else "#f87171" for q in ruinquoten]},
    }

    # KPI-Werte berechnen
    median_stand = statistics.median([k["kontostand"] for k in aktiv]) if aktiv else 0.0
    bah_stand = bah["kontostand"] if bah else None
    besser_bah_pct = (
        sum(1 for k in aktiv if k["kontostand"] > bah_stand) / len(aktiv) * 100
        if aktiv and bah_stand is not None else 0.0
    )
    M = len(breakout)
    bonferroni = math.sqrt(2 * math.log(M)) if M > 1 else 0.0
    ambivalent_pct = gesamt_ambivalent / gesamt_trades * 100 if gesamt_trades > 0 else 0.0

    # Tabelle: alle Breakout-Konten (JSON fuer JavaScript)
    tabellen_daten = [
        {
            "id": k["konto_id"],
            "n": k["n"],
            "tp": k["tp"],
            "sl": k["sl"],
            "hebel": k["hebel"],
            "kontostand": round(k["kontostand"], 2),
            "status": k["status"],
            "delta_pct": round((k["kontostand"] / 100.0 - 1) * 100, 1),
        }
        for k in breakout
    ]

    # --- Always-Long Daten ---
    al_konten = [k for k in alle_konten if k["strategie"] == "always_long"]
    al_aktiv = [k for k in al_konten if k["status"] == "aktiv"]
    al_ruiniert = [k for k in al_konten if k["status"] == "ruiniert"]
    al_median = statistics.median([k["kontostand"] for k in al_aktiv]) if al_aktiv else 0.0

    al_top10 = sorted(al_aktiv, key=lambda k: k["kontostand"], reverse=True)[:10]
    al_equity_traces = []
    al_hat_equity = False
    for k in al_top10:
        history = get_equity_history(conn, k["konto_id"])
        if history:
            al_hat_equity = True
            al_equity_traces.append({
                "x": [e["zeit"] for e in history],
                "y": [e["kontostand"] for e in history],
                "type": "scatter",
                "mode": "lines",
                "name": k["konto_id"][:20],
                "line": {"width": 2},
            })

    al_tabellen_daten = [
        {
            "id": k["konto_id"],
            "tp": k["tp"],
            "sl": k["sl"],
            "hebel": k["hebel"],
            "kontostand": round(k["kontostand"], 2),
            "status": k["status"],
            "delta_pct": round((k["kontostand"] / 100.0 - 1) * 100, 1),
        }
        for k in al_konten
    ]

    conn.close()

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    equity_hinweis = "" if hat_equity_daten else """
        <div class="empty-state">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M3 17l4-8 4 5 3-3 4 6"/>
                <path d="M21 21H3"/>
            </svg>
            <p>Noch keine Equity-Daten</p>
            <small>Equity wird alle 15 Minuten gespeichert — komm bald wieder.</small>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paper-Trader Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: #0b0d14;
            color: #c9d1e0;
            min-height: 100vh;
            overflow-x: hidden;
        }}

        /* ─── Topbar ─── */
        .topbar {{
            position: sticky;
            top: 0;
            z-index: 100;
            background: rgba(11,13,20,0.92);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid #1e2235;
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
        }}
        .topbar-title {{
            font-size: 1.1rem;
            font-weight: 700;
            color: #e2e8f0;
            letter-spacing: -0.01em;
        }}
        .topbar-title span {{ color: #7c85f5; }}
        .topbar-meta {{
            font-size: 0.78rem;
            color: #64748b;
        }}
        .refresh-btn {{
            background: #1e2235;
            border: 1px solid #2d3150;
            color: #94a3b8;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8rem;
            transition: background 0.15s;
            white-space: nowrap;
        }}
        .refresh-btn:hover {{ background: #2d3150; color: #e2e8f0; }}

        /* ─── Layout ─── */
        .page {{ padding: 24px; max-width: 1600px; margin: 0 auto; }}

        /* ─── KPI Cards ─── */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }}
        .kpi {{
            background: #111420;
            border: 1px solid #1e2235;
            border-radius: 10px;
            padding: 16px 20px;
        }}
        .kpi-label {{
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #64748b;
            margin-bottom: 6px;
        }}
        .kpi-value {{
            font-size: 1.65rem;
            font-weight: 700;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
            line-height: 1;
        }}
        .kpi-sub {{
            font-size: 0.75rem;
            color: #64748b;
            margin-top: 4px;
        }}
        .kpi-value.green {{ color: #4ade80; }}
        .kpi-value.red {{ color: #f87171; }}
        .kpi-value.yellow {{ color: #fbbf24; }}

        /* ─── Section ─── */
        .section {{ margin-bottom: 24px; }}
        .section-title {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #64748b;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #1e2235;
        }}

        /* ─── Charts Grid ─── */
        .charts-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }}
        @media (max-width: 768px) {{
            .charts-grid {{ grid-template-columns: 1fr; }}
        }}

        .chart-card {{
            background: #111420;
            border: 1px solid #1e2235;
            border-radius: 10px;
            padding: 16px;
            overflow: hidden;
        }}
        .chart-card.full {{ grid-column: 1 / -1; }}
        .chart-card-title {{
            font-size: 0.78rem;
            color: #94a3b8;
            margin-bottom: 12px;
            font-weight: 600;
        }}
        .chart-inner {{ width: 100%; height: 280px; }}
        .chart-inner.tall {{ height: 340px; }}

        /* ─── Empty state ─── */
        .empty-state {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 280px;
            color: #334155;
            gap: 8px;
            text-align: center;
        }}
        .empty-state p {{ color: #64748b; font-size: 0.9rem; }}
        .empty-state small {{ color: #334155; font-size: 0.78rem; }}

        /* ─── Table ─── */
        .table-wrap {{
            background: #111420;
            border: 1px solid #1e2235;
            border-radius: 10px;
            overflow: hidden;
        }}
        .table-search {{
            padding: 12px 16px;
            border-bottom: 1px solid #1e2235;
            display: flex;
            gap: 12px;
            align-items: center;
        }}
        .table-search input {{
            background: #0b0d14;
            border: 1px solid #1e2235;
            color: #c9d1e0;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 0.82rem;
            width: 220px;
            outline: none;
        }}
        .table-search input:focus {{ border-color: #7c85f5; }}
        .table-search label {{ font-size: 0.78rem; color: #64748b; }}
        .table-container {{ overflow-x: auto; max-height: 420px; overflow-y: auto; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82rem;
            font-variant-numeric: tabular-nums;
        }}
        thead {{ position: sticky; top: 0; z-index: 10; }}
        th {{
            background: #16192a;
            padding: 10px 14px;
            text-align: left;
            color: #64748b;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            user-select: none;
        }}
        th:hover {{ color: #c9d1e0; }}
        th .sort-icon {{ margin-left: 4px; opacity: 0.4; }}
        th.sort-asc .sort-icon::after {{ content: '▲'; opacity: 1; }}
        th.sort-desc .sort-icon::after {{ content: '▼'; opacity: 1; }}
        td {{
            padding: 9px 14px;
            border-bottom: 1px solid #131625;
            white-space: nowrap;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: #13162a; }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 600;
        }}
        .badge-aktiv {{ background: #14532d44; color: #4ade80; border: 1px solid #14532d; }}
        .badge-ruiniert {{ background: #7f1d1d44; color: #f87171; border: 1px solid #7f1d1d; }}
        .pos {{ color: #4ade80; }}
        .neg {{ color: #f87171; }}
        .neutral {{ color: #94a3b8; }}

        /* ─── Footer ─── */
        .footer {{
            text-align: center;
            padding: 32px 24px 16px;
            color: #334155;
            font-size: 0.75rem;
        }}
    </style>
</head>
<body>

<div class="topbar">
    <div class="topbar-title"><span>●</span> Paper-Trader</div>
    <div class="topbar-meta">Letzte Kerze: {letzte_kerze}</div>
    <button class="refresh-btn" onclick="location.reload()">↺ Aktualisieren</button>
</div>

<div class="page">

    <!-- KPI Cards -->
    <div class="kpi-grid">
        <div class="kpi">
            <div class="kpi-label">Aktive Konten</div>
            <div class="kpi-value">{len(aktiv)}</div>
            <div class="kpi-sub">von {len(breakout)} gesamt</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Ruiniert</div>
            <div class="kpi-value {'red' if ruiniert_konten else 'green'}">{len(ruiniert_konten)}</div>
            <div class="kpi-sub">{f'{len(ruiniert_konten)/len(breakout)*100:.1f}%' if breakout else '—'} Ruinquote</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Median Kontostand</div>
            <div class="kpi-value {'green' if median_stand >= 100 else 'red'}">{median_stand:.2f}</div>
            <div class="kpi-sub">USDC (Start: 100)</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Buy-and-Hold</div>
            <div class="kpi-value">{f'{bah_stand:.2f}' if bah_stand is not None else '—'}</div>
            <div class="kpi-sub">USDC Benchmark</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Konten &gt; BaH</div>
            <div class="kpi-value {'green' if besser_bah_pct > 50 else 'yellow'}">{besser_bah_pct:.0f}%</div>
            <div class="kpi-sub">schlagen den Benchmark</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Trades gesamt</div>
            <div class="kpi-value">{gesamt_trades}</div>
            <div class="kpi-sub">{ambivalent_pct:.1f}% ambivalente Kerzen</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Bonferroni-Schwelle</div>
            <div class="kpi-value">{bonferroni:.2f}<span style="font-size:1rem;color:#64748b"> σ</span></div>
            <div class="kpi-sub">bei M={M} Varianten</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Erstellt</div>
            <div class="kpi-value" style="font-size:0.9rem;padding-top:4px">{now}</div>
            <div class="kpi-sub">UTC</div>
        </div>
    </div>

    <!-- Equity-Kurven -->
    <div class="section">
        <div class="section-title">Equity-Kurven — Top 10 Konten</div>
        <div class="chart-card full">
            {'<div id="equity-chart" class="chart-inner tall"></div>' if hat_equity_daten else equity_hinweis}
        </div>
    </div>

    <!-- Histogram + Ruinquote -->
    <div class="section">
        <div class="section-title">Verteilung & Ruinquoten</div>
        <div class="charts-grid">
            <div class="chart-card">
                <div class="chart-card-title">Kontostand-Verteilung (alle Konten)</div>
                <div id="histogram-chart" class="chart-inner"></div>
            </div>
            <div class="chart-card">
                <div class="chart-card-title">Ruinquote je Hebelstufe</div>
                <div id="ruin-chart" class="chart-inner"></div>
            </div>
        </div>
    </div>

    <!-- Tabelle -->
    <div class="section">
        <div class="section-title">Alle Konten</div>
        <div class="table-wrap">
            <div class="table-search">
                <label>Suche:</label>
                <input type="text" id="search-input" placeholder="Konto-ID, Hebel..." oninput="filterTable()">
                <label style="margin-left:auto">
                    <input type="checkbox" id="only-aktiv" onchange="filterTable()"> Nur aktive
                </label>
            </div>
            <div class="table-container">
                <table id="konten-tabelle">
                    <thead>
                        <tr>
                            <th onclick="sortTable(0)">Konto-ID <span class="sort-icon"></span></th>
                            <th onclick="sortTable(1)">N <span class="sort-icon"></span></th>
                            <th onclick="sortTable(2)">TP% <span class="sort-icon"></span></th>
                            <th onclick="sortTable(3)">SL% <span class="sort-icon"></span></th>
                            <th onclick="sortTable(4)">Hebel <span class="sort-icon"></span></th>
                            <th onclick="sortTable(5)">Kontostand <span class="sort-icon"></span></th>
                            <th onclick="sortTable(6)">Δ vs 100 <span class="sort-icon"></span></th>
                            <th onclick="sortTable(7)">Status <span class="sort-icon"></span></th>
                        </tr>
                    </thead>
                    <tbody id="tabellen-body"></tbody>
                </table>
            </div>
        </div>
    </div>

</div>

<!-- Always-Long Sektion -->
<div class="page" style="padding-top:0">

    <div class="section">
        <div class="section-title" style="color:#f59e0b;border-color:#f59e0b33">Always-Long Strategie — Eigene Sektion</div>

        <!-- Always-Long KPIs -->
        <div class="kpi-grid" style="margin-bottom:16px">
            <div class="kpi">
                <div class="kpi-label">Aktive Konten</div>
                <div class="kpi-value">{len(al_aktiv)}</div>
                <div class="kpi-sub">von {len(al_konten)} gesamt</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Ruiniert</div>
                <div class="kpi-value {'red' if al_ruiniert else 'green'}">{len(al_ruiniert)}</div>
                <div class="kpi-sub">{f'{len(al_ruiniert)/len(al_konten)*100:.1f}%' if al_konten else '—'} Ruinquote</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Median Kontostand</div>
                <div class="kpi-value {'green' if al_median >= 100 else 'red'}">{al_median:.2f}</div>
                <div class="kpi-sub">USDC (Start: 100)</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Bearish-Filter</div>
                <div class="kpi-value" style="font-size:1rem;padding-top:6px">7 von 10</div>
                <div class="kpi-sub">rote 1m-Kerzen = kein Entry</div>
            </div>
        </div>

        <!-- Equity-Kurven -->
        <div class="chart-card full" style="margin-bottom:16px">
            <div class="chart-card-title">Equity-Kurven Top 10 Always-Long Konten</div>
            {'<div id="al-equity-chart" class="chart-inner tall"></div>' if al_hat_equity else '<div class="empty-state"><p>Noch keine Equity-Daten</p><small>Equity wird alle 15 Minuten gespeichert.</small></div>'}
        </div>

        <!-- Always-Long Tabelle -->
        <div class="table-wrap">
            <div class="table-search">
                <label>Suche:</label>
                <input type="text" id="al-search-input" placeholder="Konto-ID, Hebel..." oninput="filterAlTable()">
                <label style="margin-left:auto">
                    <input type="checkbox" id="al-only-aktiv" onchange="filterAlTable()"> Nur aktive
                </label>
            </div>
            <div class="table-container">
                <table id="al-konten-tabelle">
                    <thead>
                        <tr>
                            <th onclick="sortAlTable(0)">Konto-ID <span class="sort-icon"></span></th>
                            <th onclick="sortAlTable(1)">TP% <span class="sort-icon"></span></th>
                            <th onclick="sortAlTable(2)">SL% <span class="sort-icon"></span></th>
                            <th onclick="sortAlTable(3)">Hebel <span class="sort-icon"></span></th>
                            <th onclick="sortAlTable(4)">Kontostand <span class="sort-icon"></span></th>
                            <th onclick="sortAlTable(5)">Δ vs 100 <span class="sort-icon"></span></th>
                            <th onclick="sortAlTable(6)">Status <span class="sort-icon"></span></th>
                        </tr>
                    </thead>
                    <tbody id="al-tabellen-body"></tbody>
                </table>
            </div>
        </div>
    </div>

</div>

<div class="footer">Paper-Trader — kein echtes Geld — {now}</div>

<script>
const ALLE_DATEN = {json.dumps(tabellen_daten)};
let gefilterteDaten = [...ALLE_DATEN];
let sortCol = 5;
let sortAsc = false;

const plotLayout = (title) => ({{
    title: {{ text: title, font: {{ size: 13, color: '#94a3b8' }}, x: 0 }},
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: {{ color: '#94a3b8', size: 11 }},
    margin: {{ t: 36, r: 16, b: 48, l: 56 }},
    xaxis: {{ gridcolor: '#1e2235', zerolinecolor: '#1e2235', tickfont: {{ size: 10 }} }},
    yaxis: {{ gridcolor: '#1e2235', zerolinecolor: '#1e2235', tickfont: {{ size: 10 }} }},
    legend: {{ bgcolor: 'transparent', font: {{ size: 10 }} }},
    showlegend: true,
}});

const plotConfig = {{ responsive: true, displayModeBar: false }};

{'Plotly.newPlot("equity-chart",' + json.dumps(equity_traces) + ', {...plotLayout(""), ...{xaxis: {gridcolor:"#1e2235",zerolinecolor:"#1e2235"}, yaxis: {title: {text:"USDC",font:{size:10}},gridcolor:"#1e2235",zerolinecolor:"#1e2235"}}}, plotConfig);' if hat_equity_daten else ''}

Plotly.newPlot('histogram-chart', {json.dumps([histogram_trace])}, {{
    ...plotLayout(''),
    xaxis: {{ title: {{ text: 'Kontostand (USDC)', font: {{ size: 10 }} }}, gridcolor: '#1e2235', zerolinecolor: '#1e2235' }},
    yaxis: {{ title: {{ text: 'Anzahl Konten', font: {{ size: 10 }} }}, gridcolor: '#1e2235', zerolinecolor: '#1e2235' }},
    showlegend: false,
}}, plotConfig);

Plotly.newPlot('ruin-chart', {json.dumps([ruin_trace])}, {{
    ...plotLayout(''),
    xaxis: {{ title: {{ text: 'Hebel', font: {{ size: 10 }} }}, gridcolor: '#1e2235', zerolinecolor: '#1e2235' }},
    yaxis: {{ title: {{ text: 'Ruinquote (%)', font: {{ size: 10 }} }}, gridcolor: '#1e2235', zerolinecolor: '#1e2235', range: [0, 100] }},
    showlegend: false,
}}, plotConfig);

function renderTable(data) {{
    const tbody = document.getElementById('tabellen-body');
    if (data.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#334155;padding:32px">Keine Konten gefunden</td></tr>';
        return;
    }}
    tbody.innerHTML = data.map(k => {{
        const dp = k.delta_pct;
        const dc = dp > 0 ? 'pos' : dp < 0 ? 'neg' : 'neutral';
        const vorzeichen = dp > 0 ? '+' : '';
        const badge = k.status === 'aktiv'
            ? '<span class="badge badge-aktiv">aktiv</span>'
            : '<span class="badge badge-ruiniert">ruiniert</span>';
        return `<tr>
            <td style="font-family:monospace;font-size:0.78rem">${{k.id}}</td>
            <td>${{k.n}}</td>
            <td>${{k.tp.toFixed(2)}}</td>
            <td>${{k.sl.toFixed(2)}}</td>
            <td>${{k.hebel}}x</td>
            <td style="font-weight:600">${{k.kontostand.toFixed(2)}}</td>
            <td class="${{dc}}">${{vorzeichen}}${{dp.toFixed(1)}}%</td>
            <td>${{badge}}</td>
        </tr>`;
    }}).join('');
}}

function filterTable() {{
    const q = document.getElementById('search-input').value.toLowerCase();
    const nurAktiv = document.getElementById('only-aktiv').checked;
    gefilterteDaten = ALLE_DATEN.filter(k =>
        (!nurAktiv || k.status === 'aktiv') &&
        (!q || k.id.toLowerCase().includes(q) || String(k.hebel).includes(q))
    );
    sortAndRender();
}}

const keys = ['id','n','tp','sl','hebel','kontostand','delta_pct','status'];

function sortTable(col) {{
    const ths = document.querySelectorAll('th');
    ths.forEach((th, i) => {{
        th.classList.remove('sort-asc','sort-desc');
        if (i === col) th.classList.add(sortAsc && sortCol === col ? 'sort-desc' : 'sort-asc');
    }});
    if (sortCol === col) sortAsc = !sortAsc; else {{ sortCol = col; sortAsc = true; }}
    sortAndRender();
}}

function sortAndRender() {{
    const key = keys[sortCol];
    const sorted = [...gefilterteDaten].sort((a,b) => {{
        const av = a[key], bv = b[key];
        const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv));
        return sortAsc ? cmp : -cmp;
    }});
    renderTable(sorted);
}}

// Initiales Render: nach Kontostand absteigend
sortCol = 5; sortAsc = false;
sortAndRender();

// Auto-refresh alle 60 Sekunden
setTimeout(() => location.reload(), 60000);

// --- Always-Long Tabelle ---
const AL_ALLE_DATEN = {json.dumps(al_tabellen_daten)};
let alGefilterteDaten = [...AL_ALLE_DATEN];
let alSortCol = 4;
let alSortAsc = false;
const alKeys = ['id','tp','sl','hebel','kontostand','delta_pct','status'];

{'Plotly.newPlot("al-equity-chart",' + json.dumps(al_equity_traces) + ', {...plotLayout(""), ...{xaxis: {gridcolor:"#1e2235",zerolinecolor:"#1e2235"}, yaxis: {title: {text:"USDC",font:{size:10}},gridcolor:"#1e2235",zerolinecolor:"#1e2235"}}}, plotConfig);' if al_hat_equity else ''}

function renderAlTable(data) {{
    const tbody = document.getElementById('al-tabellen-body');
    if (data.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#334155;padding:32px">Keine Konten gefunden</td></tr>';
        return;
    }}
    tbody.innerHTML = data.map(k => {{
        const dp = k.delta_pct;
        const dc = dp > 0 ? 'pos' : dp < 0 ? 'neg' : 'neutral';
        const vorzeichen = dp > 0 ? '+' : '';
        const badge = k.status === 'aktiv'
            ? '<span class="badge badge-aktiv">aktiv</span>'
            : '<span class="badge badge-ruiniert">ruiniert</span>';
        return `<tr>
            <td style="font-family:monospace;font-size:0.78rem">${{k.id}}</td>
            <td>${{k.tp.toFixed(2)}}</td>
            <td>${{k.sl.toFixed(2)}}</td>
            <td>${{k.hebel}}x</td>
            <td style="font-weight:600">${{k.kontostand.toFixed(2)}}</td>
            <td class="${{dc}}">${{vorzeichen}}${{dp.toFixed(1)}}%</td>
            <td>${{badge}}</td>
        </tr>`;
    }}).join('');
}}

function filterAlTable() {{
    const q = document.getElementById('al-search-input').value.toLowerCase();
    const nurAktiv = document.getElementById('al-only-aktiv').checked;
    alGefilterteDaten = AL_ALLE_DATEN.filter(k =>
        (!nurAktiv || k.status === 'aktiv') &&
        (!q || k.id.toLowerCase().includes(q) || String(k.hebel).includes(q))
    );
    sortAndRenderAl();
}}

function sortAlTable(col) {{
    const ths = document.querySelectorAll('#al-konten-tabelle th');
    ths.forEach((th, i) => {{
        th.classList.remove('sort-asc','sort-desc');
        if (i === col) th.classList.add(alSortAsc && alSortCol === col ? 'sort-desc' : 'sort-asc');
    }});
    if (alSortCol === col) alSortAsc = !alSortAsc; else {{ alSortCol = col; alSortAsc = true; }}
    sortAndRenderAl();
}}

function sortAndRenderAl() {{
    const key = alKeys[alSortCol];
    const sorted = [...alGefilterteDaten].sort((a,b) => {{
        const av = a[key], bv = b[key];
        const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv));
        return alSortAsc ? cmp : -cmp;
    }});
    renderAlTable(sorted);
}}

alSortCol = 4; alSortAsc = false;
sortAndRenderAl();
</script>
</body>
</html>"""

    with open(ausgabe, "w", encoding="utf-8") as f:
        f.write(html)

    return ausgabe


def main():
    parser = argparse.ArgumentParser(description="HTML-Dashboard generieren")
    parser.add_argument("--db-pfad", default="paper.db")
    parser.add_argument("--ausgabe", default="dashboard.html")
    args = parser.parse_args()
    pfad = erstelle_dashboard(db_pfad=args.db_pfad, ausgabe=args.ausgabe)
    print(f"Dashboard erstellt: {pfad}")


if __name__ == "__main__":
    main()
