"""Parameter-Grid fuer Paper-Trading generieren und validieren.

Dieses Modul:
- Generiert alle gueltigen Parameterkombinationen (bis zu 1280)
- Filtert mechanisch unmoegliche Kombinationen (SL >= Liquidationsdistanz)
- Markiert kostendominierte Kombinationen (TP < 3x Rundenkosten)
- Gibt immer Buy-and-Hold und Zufallsstrategie als Vergleichsbasis mit
"""

from itertools import product

# --- Kosten und Grenzen ---
TAKER_FEE = 0.00045    # 0.045% pro Order
SPREAD = 0.0001         # 0.01% geschaetzter Spread
# Rundenkosten = Einstieg + Ausstieg, jeweils Taker-Fee + halber Spread
RUNDENKOSTEN = 2 * (TAKER_FEE + SPREAD)  # ~0.11%

STARTKAPITAL = 100.0   # USDC pro Konto
MIN_NOTIONAL = 10.0    # Mindestordergröße Hyperliquid in USD

# --- Parameter-Grid ---
N_WERTE        = [10, 20, 50, 100]
TP_WERTE       = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0]  # in Prozent
SL_WERTE       = [0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]  # in Prozent
HEBEL_WERTE    = [1, 3, 5, 10, 25]

# --- Testmodus: nur 6 Konten ---
TESTMODUS_PARAMS = {
    "n":     [20],
    "tp":    [1.0, 2.0],
    "sl":    [0.5],
    "hebel": [1, 5, 25],
}


def validate_combination(n: int, tp: float, sl: float, hebel: int) -> tuple[bool, str]:
    """Prueft eine Parameterkombination auf Gueltigkeit.

    Gibt (gueltig, grund) zurueck:
    - (False, "mechanisch unmoeglich"): SL >= Liquidationsdistanz
    - (True, "kostendominiert"):        TP < 3x Rundenkosten
    - (True, ""):                       normal gueltig
    """
    # Liquidationsdistanz in Prozent: ca. 90% des Kehrwerts des Hebels
    # (10% Sicherheitspuffer gegenueber der theoretischen 100%-Grenze)
    liquidation_pct = (1.0 / hebel) * 0.9 * 100

    if sl >= liquidation_pct:
        return False, "mechanisch unmoeglich"

    # Rundenkosten in Prozent
    rundenkosten_pct = RUNDENKOSTEN * 100  # ~0.11%
    if tp < 3 * rundenkosten_pct:
        return True, "kostendominiert"

    return True, ""


def konto_id_from_params(
    n: int, tp: float, sl: float, hebel: int,
    strategie: str = "breakout",
) -> str:
    """Erzeugt eine eindeutige, menschenlesbare Konto-ID.

    Format: brk_20_1.0_0.5_5 (Strategie_N_TP_SL_Hebel)
    """
    praefix = {"breakout": "brk", "buy_and_hold": "bah", "zufall": "rnd"}
    p = praefix.get(strategie, strategie)
    return f"{p}_{n}_{tp}_{sl}_{hebel}"


def generate_grid(testmodus: bool = False) -> list[dict]:
    """Erzeugt alle gueltigen Parameterkombinationen als Liste von Dicts.

    Im Testmodus (--testmodus) werden nur 6 Konten erzeugt.
    Immer enthalten: Buy-and-Hold und Zufallsstrategie als Vergleich.

    Jedes Dict enthaelt:
    - konto_id, n, tp, sl, hebel, strategie, startkapital, warnung
    """
    if testmodus:
        n_werte    = TESTMODUS_PARAMS["n"]
        tp_werte   = TESTMODUS_PARAMS["tp"]
        sl_werte   = TESTMODUS_PARAMS["sl"]
        hebel_werte = TESTMODUS_PARAMS["hebel"]
    else:
        n_werte    = N_WERTE
        tp_werte   = TP_WERTE
        sl_werte   = SL_WERTE
        hebel_werte = HEBEL_WERTE

    grid = []

    for n, tp, sl, hebel in product(n_werte, tp_werte, sl_werte, hebel_werte):
        gueltig, grund = validate_combination(n, tp, sl, hebel)
        if not gueltig:
            # Mechanisch unmoegliche Kombination wird uebersprungen
            continue

        grid.append({
            "konto_id":    konto_id_from_params(n, tp, sl, hebel),
            "n":           n,
            "tp":          tp,
            "sl":          sl,
            "hebel":       hebel,
            "strategie":   "breakout",
            "startkapital": STARTKAPITAL,
            "warnung":     grund if grund else None,
        })

    # Buy-and-Hold: einmal kaufen, bis zum Ende halten
    grid.append({
        "konto_id":    "bah_0_0_0_1",
        "n":           0,
        "tp":          0.0,
        "sl":          0.0,
        "hebel":       1,
        "strategie":   "buy_and_hold",
        "startkapital": STARTKAPITAL,
        "warnung":     None,
    })

    # Zufallsstrategie: Vergleichsbasis mit gleicher Handelsfrequenz
    grid.append({
        "konto_id":    "rnd_0_0_0_1",
        "n":           0,
        "tp":          0.0,
        "sl":          0.0,
        "hebel":       1,
        "strategie":   "zufall",
        "startkapital": STARTKAPITAL,
        "warnung":     None,
    })

    return grid
