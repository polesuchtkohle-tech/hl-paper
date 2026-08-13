"""Statisches HTML-Dashboard fuer den Paper-Trader.

Generiert eine einzelne HTML-Datei mit Plotly-Charts.
Oeffne die Datei im Browser nach Aufruf.

Aufruf: uv run python dashboard.py [--db-pfad paper.db] [--ausgabe dashboard.html]
"""

import argparse
import json
import os
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

    # Equity-Kurven der Top 10
    top10 = aktiv[:10]
    equity_traces = []
    for k in top10:
        history = get_equity_history(conn, k["konto_id"])
        if history:
            zeiten = [e["zeit"] for e in history]
            staende = [e["kontostand"] for e in history]
            trace = {
                "x": zeiten,
                "y": staende,
                "type": "scatter",
                "mode": "lines",
                "name": k["konto_id"][:25],
            }
            equity_traces.append(trace)

    # Histogram: Endergebnisse aller Breakout-Konten
    alle_staende = [k["kontostand"] for k in breakout]
    histogram_trace = {
        "x": alle_staende,
        "type": "histogram",
        "nbinsx": 30,
        "name": "Kontostand-Verteilung",
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
    }

    # Tabelle: alle Konten (JSON fuer JavaScript)
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

    conn.close()

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paper-Trader Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f1117; color: #e0e0e0; margin: 0; padding: 20px; }}
        h1, h2 {{ color: #7c85f5; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }}
        .chart {{ background: #1a1d2e; border-radius: 8px; padding: 15px; }}
        .full {{ grid-column: 1 / -1; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
        th {{ background: #2a2d3e; padding: 8px; text-align: left; cursor: pointer; }}
        th:hover {{ background: #3a3d4e; }}
        td {{ padding: 6px 8px; border-bottom: 1px solid #2a2d3e; }}
        tr:hover {{ background: #1f2235; }}
        .aktiv {{ color: #4ade80; }}
        .ruiniert {{ color: #f87171; }}
        .pos {{ color: #4ade80; }}
        .neg {{ color: #f87171; }}
        .meta {{ color: #888; font-size: 0.85em; margin-bottom: 20px; }}
    </style>
</head>
<body>
<h1>Paper-Trader Dashboard</h1>
<p class="meta">Erstellt: {now} | Konten: {len(aktiv)} aktiv / {len(ruiniert_konten)} ruiniert</p>

<div class="grid">
    <div class="chart full" id="equity-chart"></div>
    <div class="chart" id="histogram-chart"></div>
    <div class="chart" id="ruin-chart"></div>
</div>

<h2>Alle Konten</h2>
<div class="chart full">
<table id="konten-tabelle">
    <thead>
        <tr>
            <th onclick="sortTable(0)">Konto-ID</th>
            <th onclick="sortTable(1)">N</th>
            <th onclick="sortTable(2)">TP%</th>
            <th onclick="sortTable(3)">SL%</th>
            <th onclick="sortTable(4)">Hebel</th>
            <th onclick="sortTable(5)">Kontostand</th>
            <th onclick="sortTable(6)">&#916; vs 100</th>
            <th onclick="sortTable(7)">Status</th>
        </tr>
    </thead>
    <tbody id="tabellen-body">
    </tbody>
</table>
</div>

<script>
const daten = {json.dumps(tabellen_daten)};
const equityTraces = {json.dumps(equity_traces)};
const histogramTrace = {json.dumps([histogram_trace])};
const ruinTrace = {json.dumps([ruin_trace])};

// Equity-Kurven
Plotly.newPlot('equity-chart', equityTraces, {{
    title: 'Equity-Kurven Top 10 Konten',
    paper_bgcolor: '#1a1d2e',
    plot_bgcolor: '#1a1d2e',
    font: {{ color: '#e0e0e0' }},
    xaxis: {{ title: 'Zeit' }},
    yaxis: {{ title: 'Kontostand (USDC)' }},
}}, {{responsive: true}});

// Histogram
Plotly.newPlot('histogram-chart', histogramTrace, {{
    title: 'Verteilung aller Kontostaende',
    paper_bgcolor: '#1a1d2e',
    plot_bgcolor: '#1a1d2e',
    font: {{ color: '#e0e0e0' }},
    xaxis: {{ title: 'Kontostand (USDC)' }},
    yaxis: {{ title: 'Anzahl Konten' }},
}}, {{responsive: true}});

// Ruinquote
Plotly.newPlot('ruin-chart', ruinTrace, {{
    title: 'Ruinquote je Hebelstufe',
    paper_bgcolor: '#1a1d2e',
    plot_bgcolor: '#1a1d2e',
    font: {{ color: '#e0e0e0' }},
    xaxis: {{ title: 'Hebel' }},
    yaxis: {{ title: 'Ruinquote (%)' }},
}}, {{responsive: true}});

// Tabelle befuellen
function renderTable(data) {{
    const tbody = document.getElementById('tabellen-body');
    tbody.innerHTML = '';
    data.forEach(k => {{
        const delta_class = k.delta_pct >= 0 ? 'pos' : 'neg';
        const vorzeichen = k.delta_pct >= 0 ? '+' : '';
        tbody.innerHTML += `<tr>
            <td>${{k.id}}</td>
            <td>${{k.n}}</td>
            <td>${{k.tp.toFixed(2)}}</td>
            <td>${{k.sl.toFixed(2)}}</td>
            <td>${{k.hebel}}x</td>
            <td>${{k.kontostand.toFixed(2)}}</td>
            <td class="${{delta_class}}">${{vorzeichen}}${{k.delta_pct.toFixed(1)}}%</td>
            <td class="${{k.status}}">${{k.status}}</td>
        </tr>`;
    }});
}}

renderTable(daten);

// Einfaches Sortieren
let sortDir = {{}};
function sortTable(col) {{
    const keys = ['id','n','tp','sl','hebel','kontostand','delta_pct','status'];
    const key = keys[col];
    sortDir[col] = !sortDir[col];
    const sorted = [...daten].sort((a, b) => {{
        const av = a[key], bv = b[key];
        if (typeof av === 'number') return sortDir[col] ? av - bv : bv - av;
        return sortDir[col] ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    renderTable(sorted);
}}
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
