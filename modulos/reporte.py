"""
reporte.py — Arma el mensaje de Telegram para un activo.

Enfoque TÉCNICO-FIRST (pedido de Sebastián): el técnico manda y la valuación
queda como contexto mínimo indispensable para operar. Formato compacto y visual,
con un bloque de "Niveles para operar" en monoespaciado (alineado como tabla).
Mantiene todo explicado en criollo, pero corto.
"""

from modulos.tecnico import analisis_tecnico_completo
from modulos.valuacion import evaluar_valuacion

EMOJI = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}

_RSI_CORTO = {
    "sobreventa": "sobrevendido",
    "acercandose_sobreventa": "cerca de sobreventa",
    "neutral": "zona neutral",
    "acercandose_sobrecompra": "cerca de sobrecompra",
    "sobrecompra": "sobrecomprado",
}


def _voto_emoji(signo):
    """Convierte el voto de un factor (puede ser ±2 en el RSI) a un emoji de dirección."""
    if signo > 0:
        return "🟢"
    if signo < 0:
        return "🔴"
    return "⚪"


def _rsi_corto(rsi_ctx):
    return f"RSI {rsi_ctx['valor']} · {_RSI_CORTO[rsi_ctx['estado']]}"


def _pct(x):
    """Formatea un % con signo, o 's/d' si falta el dato."""
    return f"{x:+.1f}%" if x is not None else "s/d"


def _valuacion_corta(val):
    """Valuación mínima para operar: target de analistas + un tag barata/cara."""
    partes = []
    c = val.get("consenso")
    if c:
        partes.append(f"🎯 Analistas ${c['target']} ({c['upside_pct']:+.0f}%)")

    color = val.get("color")
    if "desvio_pct" in val:  # FMP disponible: comparación contra su P/E histórico
        esc = val.get("escalon", 0)
        if color == "verde":
            partes.append(f"🟢 barata (~{esc}% bajo su P/E)")
        elif color == "rojo":
            partes.append(f"🔴 cara (~{esc}% sobre su P/E)")
        else:
            partes.append("🟡 en su P/E normal")
    elif val.get("peg"):  # sin FMP, uso el PEG como referencia rápida
        peg = val["peg"]
        if peg < 1:
            partes.append(f"🟢 barata (PEG {peg})")
        elif peg <= 2:
            partes.append(f"🟡 en precio (PEG {peg})")
        else:
            partes.append(f"🔴 cara (PEG {peg})")

    return " · ".join(partes) if partes else "sin datos suficientes de valuación"


def _bloque_niveles(tec):
    """Tabla monoespaciada con los niveles clave para operar."""
    fib, ath, precio = tec["fibonacci"], tec["ath"], tec["precio"]
    filas = [
        f"{'Resistencia':<12}${fib['resistencia']:<10}{fib['resistencia_nombre']}",
        f"{'Precio':<12}${precio:<10}",
        f"{'Soporte':<12}${fib['soporte']:<10}{fib['soporte_nombre']}",
        f"{'Máx. hist.':<12}${ath['ath']:<10}{ath['desvio_pct']:+.1f}%",
    ]
    return "```\n" + "\n".join(filas) + "\n```"


def armar_reporte(ticker, timeframe=None):
    """Genera el texto completo del reporte para Telegram (técnico-first)."""
    tec = analisis_tecnico_completo(ticker, timeframe)
    sem = tec["semaforo"]
    fac = sem["factores"]

    L = []
    # ── Encabezado ──
    L.append(f"📊 *{tec['ticker']}* · ${tec['precio']}")
    L.append(f"_{tec['timeframe_nombre']}_")
    L.append("")

    # ── Señal (titular + fila visual de los 4 factores) ──
    L.append(f"{EMOJI[sem['color']]} *{sem['titulo']}*")
    fila = " ".join(_voto_emoji(fac[k]["signo"]) for k in ("rsi", "medias", "fibonacci", "divergencia"))
    L.append(fila)
    L.append("")

    # ── Lectura técnica (cada factor con su voto) ──
    L.append("*Lectura técnica*")
    L.append(f"{_voto_emoji(fac['rsi']['signo'])} {_rsi_corto(tec['rsi'])}")
    L.append(f"{_voto_emoji(fac['medias']['signo'])} {fac['medias']['texto']}")
    L.append(f"{_voto_emoji(fac['fibonacci']['signo'])} {fac['fibonacci']['texto']}")
    L.append(f"{_voto_emoji(fac['divergencia']['signo'])} {fac['divergencia']['texto'].capitalize()}")
    L.append(f"{tec['volumen']['texto']}")
    if tec["cruce"]["texto"]:
        L.append(tec["cruce"]["texto"])
    L.append("")

    # ── Niveles para operar (tabla) + Riesgo/Beneficio ──
    L.append("*Niveles para operar*")
    L.append(_bloque_niveles(tec))
    L.append(f"⚖️ {tec['riesgo_beneficio']['texto']}")
    L.append("")

    # ── Momentum + Volatilidad ──
    v = tec["variacion"]
    L.append(f"📈 *Momentum* · 1d {_pct(v['1d'])} · 1sem {_pct(v['1sem'])} · 1mes {_pct(v['1mes'])}")
    a = tec["atr"]
    L.append(f"📏 *Volatilidad* · rango ~${a['atr']} ({a['pct']}%) por vela — referencia para el stop")
    L.append("")

    # ── Valuación (contexto mínimo) ──
    if tec["es_cripto"]:
        L.append("💰 *Valuación* · cripto, sin fundamentales — lectura 100% técnica")
    else:
        val = evaluar_valuacion(tec["ticker_yf"])
        L.append(f"💰 *Valuación* · {_valuacion_corta(val)}")

    L.append("")
    L.append("_No es recomendación · confirmá en el gráfico antes de operar_")

    return "\n".join(L)
