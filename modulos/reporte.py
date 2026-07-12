"""
reporte.py — Arma el mensaje de Telegram para un activo.

Junta el análisis técnico y el de valuación en un mensaje formateado,
manteniéndolos SEPARADOS (decisión de diseño de Sebastián: no mezclar los
dos semáforos). Usa formato Markdown de Telegram.
"""

from modulos.tecnico import analisis_tecnico_completo
from modulos.valuacion import evaluar_valuacion, proyeccion_especulativa

EMOJI = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
DIVISOR = "──────────────"


def _voto_emoji(signo):
    """Convierte el voto de un factor (puede ser ±2 en el RSI) a un emoji de dirección."""
    if signo > 0:
        return "🟢"
    if signo < 0:
        return "🔴"
    return "⚪"


def armar_reporte(ticker, timeframe=None):
    """Genera el texto completo del reporte para Telegram."""
    tec = analisis_tecnico_completo(ticker, timeframe)
    proy = proyeccion_especulativa(tec)
    sem = tec["semaforo"]

    L = []
    L.append(f"*{tec['ticker']}* — ${tec['precio']}")
    L.append(f"_{tec['timeframe_nombre']}_")
    L.append("")

    # ── VALUACIÓN ──
    # A cripto no le aplican P/E, PEG ni consenso de analistas: se saltea toda
    # la parte fundamental y se muestra solo el escenario técnico especulativo.
    if tec["es_cripto"]:
        L.append("*💰 VALUACIÓN*")
        L.append(f"_No aplica a cripto (no hay P/E, PEG ni ganancias). "
                 f"Para {tec['ticker']} la lectura es técnica._")
    else:
        val = evaluar_valuacion(tec["ticker_yf"])
        L.append("*💰 VALUACIÓN*")
        L.append(val["frase_principal"])
        if val.get("frase_peg"):
            L.append(val["frase_peg"])
        if val["consenso"]:
            L.append("")
            L.append("_Horizonte:_")
            L.append(val["consenso"]["frase"])
    L.append("")
    L.append(f"{proy['aviso']}")
    L.append(f"• Alcista: {proy['alcista']}")
    L.append(f"• Bajista: {proy['bajista']}")
    L.append("")
    L.append(DIVISOR)
    L.append("")

    # ── TÉCNICO ──
    # Semáforo multifactor: el título resume la señal y cada factor muestra su
    # voto (🟢 compra / 🔴 venta / ⚪ neutral) para que se vea de dónde sale.
    fac = sem["factores"]
    L.append(f"*📊 TÉCNICO* {EMOJI[sem['color']]} {sem['titulo']}")
    L.append(f"• {tec['ath']['texto']}")
    L.append(f"• {_voto_emoji(fac['rsi']['signo'])} {tec['rsi']['texto']}")
    L.append(f"• {_voto_emoji(fac['medias']['signo'])} {tec['medias']['texto']}")
    L.append(f"• {_voto_emoji(fac['fibonacci']['signo'])} Fibonacci: {tec['fibonacci']['texto']}")
    L.append(f"• {_voto_emoji(fac['divergencia']['signo'])} {tec['divergencias']['texto']}")
    L.append(f"• {tec['volumen']['texto']}")
    L.append("")
    L.append(DIVISOR)
    L.append("")

    # ── SÍNTESIS ──
    L.append("_Recordá: valuación y técnico son dos lecturas distintas. "
             "Verificá el gráfico antes de operar. Esto no es recomendación._")

    return "\n".join(L)
