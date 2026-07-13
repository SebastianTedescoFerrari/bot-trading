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
    return "🟡"


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

    # 7) Cierre con el escenario más probable y su riesgo/beneficio
    esc = tec["escenarios"]
    fav = esc["favorito"]
    if fav == "long":
        tipo = esc["long"]["tipo"]
        if tipo == "favorable":
            P.append("El escenario más probable es un LONG (a la suba), y encima el riesgo/beneficio hasta los niveles cercanos juega a favor.")
        elif tipo in ("neutro", "malo"):
            P.append("El escenario más probable es un LONG (a la suba), aunque el riesgo/beneficio en este punto no es el ideal: quizás convenga esperar una mejor entrada.")
    elif fav == "short":
        tipo = esc["short"]["tipo"]
        if tipo == "favorable":
            P.append("El escenario más probable es un SHORT (a la baja), y el riesgo/beneficio hasta los niveles cercanos juega a favor.")
        elif tipo in ("neutro", "malo"):
            P.append("El escenario más probable es un SHORT (a la baja), aunque el riesgo/beneficio en este punto no es el ideal.")
    else:
        P.append("No hay un escenario (long ni short) que se destaque: mejor esperar a que el gráfico defina.")

    return " ".join(P)


def _bloque_niveles(tec):
    """Niveles clave explicados en palabras (qué es cada uno y para qué mirarlo)."""
    fib, ath, precio = tec["fibonacci"], tec["ath"], tec["precio"]
    return [
        f"🔺 *Resistencia ${fib['resistencia']}* — techo cercano; si lo rompe, habilita más subida.",
        f"🔹 *Precio ${precio}* — donde cotiza ahora.",
        f"🔻 *Soporte ${fib['soporte']}* — piso cercano; si aguanta puede rebotar, si lo pierde suele caer más.",
        f"🏔️ *Máx. histórico ${ath['ath']}* — está {abs(ath['desvio_pct'])}% por debajo de su récord.",
    ]


_RB_MARCA = {"favorable": "✅ favorable", "neutro": "⚖️ parejo", "malo": "❌ no conviene"}


def _rb_linea(esc, direccion):
    """Arma la línea de un escenario (long o short) con objetivo, stop y ratio."""
    res, sop = esc["resistencia"], esc["soporte"]
    if direccion == "long":
        d = esc["long"]
        cuerpo = (f"objetivo ${res} (ganás +{esc['subida_pct']}% si sube), "
                  f"stop ${sop} (perdés −{esc['bajada_pct']}% si baja)")
    else:
        d = esc["short"]
        cuerpo = (f"objetivo ${sop} (ganás +{esc['bajada_pct']}% si baja), "
                  f"stop ${res} (perdés −{esc['subida_pct']}% si sube)")

    if d["tipo"] == "pegado":
        return f"{cuerpo} — stop pegado, casi sin riesgo pero muy poco margen."
    if d["tipo"] == "sin_recorrido":
        return f"{cuerpo} — objetivo pegado, casi sin recorrido para ganar."
    return f"{cuerpo}. R:B 1:{d['ratio']} — {_RB_MARCA[d['tipo']]}"


def _escenarios_texto(tec):
    """Devuelve las líneas de la sección de escenarios (más probable + long + short)."""
    esc = tec["escenarios"]
    fav = esc["favorito"]
    L = []

    if fav == "long":
        L.append("🎯 *Más probable: LONG (al alza)* — los factores técnicos se inclinan a la suba.")
    elif fav == "short":
        L.append("🎯 *Más probable: SHORT (a la baja)* — los factores técnicos se inclinan a la baja.")
    else:
        L.append("🎯 *Sin escenario claro* — los factores están parejos; para el bot, mejor esperar.")

    marca_long = " 👈" if fav == "long" else ""
    marca_short = " 👈" if fav == "short" else ""
    L.append(f"📈 *LONG* (comprás esperando que suba){marca_long}: {_rb_linea(esc, 'long')}")
    L.append(f"📉 *SHORT* (vendés en corto esperando que baje){marca_short}: {_rb_linea(esc, 'short')}")
    return L


def _momentum_texto(tec):
    v = tec["variacion"]
    base = f"En el día {_pct(v['1d'])}, en la semana {_pct(v['1sem'])} y en el mes {_pct(v['1mes'])}."
    vals = [x for x in (v["1d"], v["1sem"], v["1mes"]) if x is not None]
    if vals and all(x > 0 for x in vals):
        base += " Viene con envión alcista."
    elif vals and all(x < 0 for x in vals):
        base += " Viene golpeada en todos los plazos."
    return base


def _zona_ath_texto(ath):
    """Qué tan barato/caro está en términos históricos, por distancia al máximo."""
    desvio = ath["desvio_pct"]
    if desvio is None:
        return None
    d = abs(desvio)
    if desvio >= -10:
        return f"Está cerca de sus máximos históricos (${ath['ath']}) — caro en términos históricos."
    etiqueta = "precio intermedio" if d <= 30 else ("zona baja" if d <= 50 else "zona históricamente barata")
    return f"Está a −{d}% de su máximo histórico (${ath['ath']}) — {etiqueta}."


def _fase_acumulacion_texto(fase):
    """Guía de acumulación según si el precio dejó de caer o no."""
    if fase == "bajando":
        return ("↘️ Pero todavía viene *cayendo*: cuidado con acumular en plena caída "
                "(\"cuchillo cayendo\"); conviene esperar a que se estabilice.")
    if fase == "lateral":
        return ("↔️ Y el precio viene *lateralizando* (dejó de caer): suele ser mejor "
                "momento para acumular de a poco que en plena caída.")
    return "↗️ Y ya viene *recuperando*: el rebote puede haber arrancado."


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
    # El volumen no vota: acompaña como confianza cuando ya hay una señal.
    vol_suffix = ""
    if sem["net"] != 0:
        est = tec["volumen"]["estado"]
        if est == "alto":
            vol_suffix = " · 🔊 volumen confirma"
        elif est == "bajo":
            vol_suffix = " · 🔈 volumen flojo"
    L.append(f"{EMOJI[sem['color']]} *{sem['titulo']}*  ·  {sem['n_acuerdo']}/4 factores{vol_suffix}")
    L.append(" ".join(_voto_emoji(fac[k]["signo"]) for k in ("rsi", "medias", "fibonacci", "divergencia")))
    L.append("")

    # ── Lectura en palabras ──
    L.append("📝 *Lectura*")
    L.append(_lectura(tec, sem))
    L.append("")

    # ── ZONA CORTO PLAZO (trading / timing) ──
    L.append("⏱️ *CORTO PLAZO — para operar (trading)*")
    L.append("_Cuándo entrar o salir: semáforo, niveles, riesgo/beneficio._")
    L.append("")

    # ── Factores técnicos (cada uno con su explicación) ──
    L.append("📊 *Factores técnicos*")
    L.append(f"{_voto_emoji(fac['rsi']['signo'])} {tec['rsi']['texto']}")
    L.append(f"{_voto_emoji(fac['medias']['signo'])} {tec['medias']['texto']}")
    if fac["fibonacci"]["signo"] > 0:
        L.append(f"🟢 Fibonacci — pegado al soporte (${fib['soporte']}); si aguanta, zona de posible rebote.")
    elif fac["fibonacci"]["signo"] < 0:
        L.append(f"🔴 Fibonacci — pegado a la resistencia (${fib['resistencia']}); zona donde suele frenarse.")
    else:
        L.append(f"🟡 Fibonacci — entre el soporte (${fib['soporte']}) y la resistencia (${fib['resistencia']}), sin pegar a ninguno.")
    L.append(f"{_voto_emoji(fac['divergencia']['signo'])} {tec['divergencias']['texto']}")
    L.append(f"{tec['volumen']['texto']}")
    if tec["cruce"]["texto"]:
        L.append(tec["cruce"]["texto"])
    L.append("")

    # ── Niveles clave ──
    L.append("🎯 *Niveles clave* (precios del gráfico para vigilar)")
    L.extend(_bloque_niveles(tec))
    L.append("")

    # ── Escenarios long / short (para trading) ──
    L.append("⚖️ *Escenarios de trade* (long vs short)")
    L.extend(_escenarios_texto(tec))
    L.append("_Recordá: el R:B 1:X = por cada 1% que arriesgás, podés ganar X%. "
             "Cuanto más alto, mejor la operación._")
    L.append("")

    # ── Momentum + Volatilidad ──
    L.append(f"📈 *Momentum:* {_momentum_texto(tec)}")
    a = tec["atr"]
    L.append(f"📏 *Volatilidad:* se mueve ~${a['atr']} ({a['pct']}%) por {tec['timeframe_unidad']} en promedio; "
             f"poné el stop más allá de esa distancia para que el ruido normal no te barra.")
    L.append("")

    # ── ZONA LARGO PLAZO (inversión) ──
    L.append("📅 *LARGO PLAZO — para invertir*")
    L.append("_Si es buena inversión de fondo, más allá del timing de hoy._")
    L.append("")
    zona = _zona_ath_texto(tec["ath"])
    fase = tec["fase"]["fase"]
    if tec["es_cripto"]:
        # Cripto no tiene P/E; la lectura de "barato/caro" es por distancia al máximo.
        L.append("💰 *Zona de precio* (cripto, sin fundamentales)")
        if zona:
            L.append(f"📉 {zona}")
            L.append(_fase_acumulacion_texto(fase))
        else:
            L.append("Lectura 100% técnica.")
    else:
        L.append("💰 *Valuación*")
        L.append(_valuacion_texto(evaluar_valuacion(tec["ticker_yf"])))
        if zona:
            L.append(f"📉 *Zona de precio:* {zona} {_fase_acumulacion_texto(fase)}")

    L.append("")
    L.append("_No es recomendación · confirmá siempre en el gráfico antes de operar._")

    return "\n".join(L)
