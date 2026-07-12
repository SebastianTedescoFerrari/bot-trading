"""
reporte.py — Arma el mensaje de Telegram para un activo.

Enfoque técnico-first pero EXPLICADO: además de los datos, incluye una "Lectura"
en palabras que interpreta la situación (comprar / vender / esperar), y cada
factor se acompaña de su explicación en criollo. Valuación y técnico van
separados. Formato con secciones claras y un bloque de niveles como tabla.
"""

from modulos.tecnico import analisis_tecnico_completo
from modulos.valuacion import evaluar_valuacion

EMOJI = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}


def _voto_emoji(signo):
    """Convierte el voto de un factor (puede ser ±2 en el RSI) a un emoji de dirección."""
    if signo > 0:
        return "🟢"
    if signo < 0:
        return "🔴"
    return "⚪"


def _pct(x):
    return f"{x:+.1f}%" if x is not None else "s/d"


# ─────────────────────────────────────────────────────────────
# Lectura en palabras: interpreta el conjunto de factores.
# ─────────────────────────────────────────────────────────────
def _lectura(tec, sem):
    net = sem["net"]
    fac = sem["factores"]
    signos = [fac[k]["signo"] for k in ("rsi", "medias", "fibonacci", "divergencia")]
    fib = tec["fibonacci"]
    P = []

    # 1) Veredicto general
    if net >= 3:
        P.append("Casi todos los factores están alineados al alza: es la señal de compra más clara que da el bot.")
    elif net == 2:
        P.append("Hay un sesgo de compra moderado: dos de los cuatro factores apuntan al alza.")
    elif net == 1:
        P.append("Aparece una compra leve, sostenida por un solo factor. Es apenas un empujoncito: mejor esperar más confirmación antes de entrar.")
    elif net == 0:
        if any(s > 0 for s in signos) and any(s < 0 for s in signos):
            P.append("Los factores se contradicen entre sí, sin un ganador claro. Momento de esperar y dejar que el gráfico defina.")
        else:
            P.append("No hay señales técnicas de peso en ninguna dirección. Momento de esperar.")
    elif net == -1:
        P.append("Aparece una venta leve, de un solo factor. Es una señal débil: mejor esperar confirmación antes de actuar.")
    elif net == -2:
        P.append("Hay un sesgo de venta moderado: dos de los cuatro factores apuntan a la baja.")
    else:
        P.append("Casi todos los factores apuntan a la baja: es la señal de venta más clara que da el bot.")

    # 2) Tendencia (medias)
    if fac["medias"]["signo"] > 0:
        P.append("El precio está por encima de sus tres medias, lo que marca una tendencia alcista de fondo.")
    elif fac["medias"]["signo"] < 0:
        P.append("El precio está por debajo de sus tres medias, lo que marca una tendencia bajista de fondo.")
    else:
        P.append("El precio está mezclado entre sus medias, sin una tendencia de fondo definida.")

    # 3) Fibonacci (solo si está pegado a un nivel)
    if fac["fibonacci"]["signo"] > 0:
        P.append(f"Además está apoyado en un soporte de Fibonacci (${fib['soporte']}), zona donde suele rebotar.")
    elif fac["fibonacci"]["signo"] < 0:
        P.append(f"Además está chocando una resistencia de Fibonacci (${fib['resistencia']}), zona donde suele frenarse.")

    # 4) RSI (solo si no es neutral)
    est = tec["rsi"]["estado"]
    if est in ("sobreventa", "acercandose_sobreventa"):
        P.append("El RSI está bajo, algo que suele anticipar rebotes (aunque puede seguir cayendo).")
    elif est in ("sobrecompra", "acercandose_sobrecompra"):
        P.append("El RSI está alto, algo que suele anticipar una pausa o corrección.")

    # 5) Divergencias
    if tec["divergencias"]["alcista"]:
        P.append("Hay una posible divergencia alcista (a confirmar mirando el gráfico).")
    elif tec["divergencias"]["bajista"]:
        P.append("Hay una posible divergencia bajista (a confirmar mirando el gráfico).")

    # 6) Volumen
    if tec["volumen"]["estado"] == "alto":
        P.append("El volumen está por encima de lo normal, lo que le da fuerza a la señal.")
    elif tec["volumen"]["estado"] == "bajo":
        P.append("El volumen está flojo, así que conviene tomar la señal con cautela (puede ser un amague).")

    # 7) Cierre con riesgo/beneficio si es relevante
    rb = tec["riesgo_beneficio"]
    if rb["estado"] == "favorable":
        P.append(f"Encima, la relación riesgo/beneficio hasta los niveles cercanos juega a favor: podés ganar más de lo que arriesgás.")
    elif rb["estado"] == "ajustado":
        P.append("Ojo que la relación riesgo/beneficio hasta los niveles cercanos es ajustada: el premio no compensa tanto el riesgo.")

    return " ".join(P)


def _bloque_niveles(tec):
    fib, ath, precio = tec["fibonacci"], tec["ath"], tec["precio"]
    filas = [
        f"{'Resistencia':<12}${fib['resistencia']:<10}{fib['resistencia_nombre']}",
        f"{'Precio':<12}${precio:<10}",
        f"{'Soporte':<12}${fib['soporte']:<10}{fib['soporte_nombre']}",
        f"{'Máx. hist.':<12}${ath['ath']:<10}{ath['desvio_pct']:+.1f}%",
    ]
    return "```\n" + "\n".join(filas) + "\n```"


def _riesgo_beneficio_texto(tec):
    rb = tec["riesgo_beneficio"]
    if rb["estado"] == "favorable":
        ratio = rb["gana_pct"] / rb["arriesga_pct"]
        return (f"Podés ganar +{rb['gana_pct']}% hasta la resistencia (${rb['resistencia']}) "
                f"arriesgando solo −{rb['arriesga_pct']}% hasta el soporte (${rb['soporte']}). "
                f"Relación 1:{ratio:.1f} — favorable ✅")
    if rb["estado"] == "ajustado":
        ratio = rb["gana_pct"] / rb["arriesga_pct"]
        return (f"Ganás +{rb['gana_pct']}% hasta la resistencia (${rb['resistencia']}) pero arriesgás "
                f"−{rb['arriesga_pct']}% hasta el soporte (${rb['soporte']}). Relación 1:{ratio:.1f} — ajustada.")
    if rb["estado"] == "en_soporte":
        return f"Está pegado al soporte (${rb['soporte']}): poco para arriesgar abajo, ojo a un posible rebote."
    return f"Está pegado a la resistencia (${rb['resistencia']}): poco recorrido arriba si no la rompe."


def _momentum_texto(tec):
    v = tec["variacion"]
    base = f"En el día {_pct(v['1d'])}, en la semana {_pct(v['1sem'])} y en el mes {_pct(v['1mes'])}."
    vals = [x for x in (v["1d"], v["1sem"], v["1mes"]) if x is not None]
    if vals and all(x > 0 for x in vals):
        base += " Viene con envión alcista."
    elif vals and all(x < 0 for x in vals):
        base += " Viene golpeada en todos los plazos."
    return base


def _valuacion_texto(val):
    P = []
    c = val.get("consenso")
    if c:
        P.append(f"Los analistas ven un objetivo de ${c['target']} ({c['upside_pct']:+.0f}% desde hoy, {c['n_analistas']} analistas).")
    if "desvio_pct" in val:  # FMP disponible
        esc = val.get("escalon", 0)
        if val["color"] == "verde":
            P.append(f"Está barata: cotiza ~{esc}% por debajo de su P/E histórico.")
        elif val["color"] == "rojo":
            P.append(f"Está cara: cotiza ~{esc}% por encima de su P/E histórico.")
        else:
            P.append("Está en su precio normal frente a su P/E histórico.")
    elif val.get("peg"):
        peg = val["peg"]
        if peg < 1:
            P.append(f"Ajustada por su crecimiento parece barata (PEG {peg}, abajo de 1 es buena señal).")
        elif peg <= 2:
            P.append(f"Ajustada por su crecimiento está en un precio razonable (PEG {peg}).")
        else:
            P.append(f"Incluso por su crecimiento se paga cara (PEG {peg}, arriba de 2 es señal de caro).")
    return " ".join(P) if P else "Sin datos suficientes de valuación."


def armar_reporte(ticker, timeframe=None):
    """Genera el reporte completo para Telegram: técnico explicado + valuación."""
    tec = analisis_tecnico_completo(ticker, timeframe)
    sem = tec["semaforo"]
    fac = sem["factores"]
    fib = tec["fibonacci"]

    L = []
    # ── Encabezado ──
    L.append(f"📊 *{tec['ticker']}* · ${tec['precio']}")
    L.append(f"_{tec['timeframe_nombre']}_")
    L.append("")

    # ── Señal (acción + nivel + fila visual de los 4 factores) ──
    L.append(f"{EMOJI[sem['color']]} *{sem['titulo']}*  ·  {sem['n_acuerdo']}/4 factores")
    L.append(" ".join(_voto_emoji(fac[k]["signo"]) for k in ("rsi", "medias", "fibonacci", "divergencia")))
    L.append("")

    # ── Lectura en palabras ──
    L.append("📝 *Lectura*")
    L.append(_lectura(tec, sem))
    L.append("")

    # ── Factores técnicos (cada uno con su explicación) ──
    L.append("📊 *Factores técnicos*")
    L.append(f"{_voto_emoji(fac['rsi']['signo'])} {tec['rsi']['texto']}")
    L.append(f"{_voto_emoji(fac['medias']['signo'])} {tec['medias']['texto']}")
    if fac["fibonacci"]["signo"] > 0:
        L.append(f"🟢 Fibonacci — pegado al soporte {fib['soporte_nombre']} (${fib['soporte']}); si aguanta, zona de posible rebote.")
    elif fac["fibonacci"]["signo"] < 0:
        L.append(f"🔴 Fibonacci — pegado a la resistencia {fib['resistencia_nombre']} (${fib['resistencia']}); zona donde suele frenarse.")
    else:
        L.append(f"⚪ Fibonacci — entre el soporte {fib['soporte_nombre']} (${fib['soporte']}) y la resistencia {fib['resistencia_nombre']} (${fib['resistencia']}), sin pegar a ninguno.")
    L.append(f"{_voto_emoji(fac['divergencia']['signo'])} {tec['divergencias']['texto']}")
    L.append(f"{tec['volumen']['texto']}")
    if tec["cruce"]["texto"]:
        L.append(tec["cruce"]["texto"])
    L.append("")

    # ── Niveles para operar + Riesgo/Beneficio ──
    L.append("🎯 *Niveles para operar*")
    L.append(_bloque_niveles(tec))
    L.append(f"⚖️ *Riesgo/Beneficio:* {_riesgo_beneficio_texto(tec)}")
    L.append("")

    # ── Momentum + Volatilidad ──
    L.append(f"📈 *Momentum:* {_momentum_texto(tec)}")
    a = tec["atr"]
    L.append(f"📏 *Volatilidad:* se mueve ~${a['atr']} ({a['pct']}%) por vela en promedio; "
             f"poné el stop más allá de esa distancia para que el ruido normal no te barra.")
    L.append("")

    # ── Valuación (contexto) ──
    if tec["es_cripto"]:
        L.append("💰 *Valuación:* es cripto, no tiene fundamentales (P/E, PEG). La lectura es 100% técnica.")
    else:
        L.append("💰 *Valuación (contexto)*")
        L.append(_valuacion_texto(evaluar_valuacion(tec["ticker_yf"])))

    L.append("")
    L.append("_No es recomendación · confirmá siempre en el gráfico antes de operar._")

    return "\n".join(L)
