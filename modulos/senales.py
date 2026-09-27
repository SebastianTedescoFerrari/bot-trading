"""
senales.py — Reglas que disparan alertas técnicas (sección 5.3 del diseño).

Todo se evalúa sobre la última vela DIARIA CERRADA (una vela en curso cambia hasta el
cierre y daría señales falsas). Única excepción, configurable: el "movimiento fuerte"
también se avisa mientras la vela del día está en curso, porque es justamente lo urgente.

Qué dispara una alerta:
  1. Nivel clave: rompe o toca un nivel de Fibonacci (retrocesos y extensiones, calculados
     con las velas ANTERIORES a la evaluada), o marca nuevo máximo/mínimo de 52 semanas.
  2. Señal técnica: RSI cruza 30 o 70, golden/death cross (EMA50/EMA200), cruce del MACD,
     divergencia RSI nueva (candidata).
  3. Movimiento fuerte: variación diaria mayor al umbral del tipo de activo.

Urgentes (salen en la corrida siguiente): 52 semanas, movimiento fuerte, golden/death cross.
El resto va al resumen diario de las 08:00.
Si el volumen de la vela evaluada es menor a 0,7x su promedio, la señal sale igual pero
marcada "baja convicción" (filtro anti-amague).
"""

from modulos.mensajes import precio
from modulos.tecnico import (
    TIMEFRAMES, bajar_datos, calcular_fibonacci, calcular_macd, calcular_volumen_relativo,
    detectar_divergencias, ema_tv, rango_52_semanas, serie_rsi, solo_velas_cerradas, vela_en_curso,
)

_NOMBRE_NIVEL = {"0.0 (máx)": "el máximo de 6 meses", "1.0 (mín)": "el mínimo de 6 meses"}


def _nombre_nivel(clave):
    if clave in _NOMBRE_NIVEL:
        return _NOMBRE_NIVEL[clave]
    if clave.startswith("ext"):
        return "la extensión Fibonacci " + clave.replace("ext ", "").replace("↓", "")
    return f"el Fibonacci {clave}"


def _senal(ticker, tipo, detalle, titulo, por_que, direccion, prioridad, urgente=False, en_curso=False):
    return {
        "clave": f"{ticker}|{tipo}|{detalle}",   # identidad para el anti-spam
        "tipo": tipo, "titulo": titulo, "por_que": por_que, "direccion": direccion,
        "prioridad": prioridad, "urgente": urgente, "en_curso": en_curso,
        "baja_conviccion": False,
    }


def evaluar_senales(df_todo, activo, umbrales, vol_minimo=0.7, intradia=True, niveles_fib=None):
    """
    Aplica las reglas a un DataFrame diario (puede traer la vela en curso al final).
    Devuelve (señales ordenadas por importancia, info) sin descargar nada: así se puede
    probar con datos históricos recortados.

    niveles_fib: qué retrocesos de Fibonacci pueden disparar alerta (None = todos; las
                 extensiones siempre cuentan).
    """
    t, tipo = activo["ticker"], activo["tipo"]

    def _p(x):   # precio con el mismo formato que el resto del mensaje (coma decimal, unidad)
        return precio(x, tipo)

    df = solo_velas_cerradas(df_todo, "día")
    info = {"precio_actual": float(df_todo["Close"].iloc[-1]), "fecha": df.index[-1].date().isoformat()}
    if len(df) < 60:
        return [], info

    prev = df.iloc[:-1]
    vela, vela_prev = df.iloc[-1], prev.iloc[-1]
    cierre, cierre_prev = float(vela["Close"]), float(vela_prev["Close"])
    fecha = info["fecha"]
    S = []

    # ── 1) Nuevo máximo / mínimo de 52 semanas (urgente) ──
    r52 = rango_52_semanas(df)
    if r52 and r52["nuevo_maximo"]:
        S.append(_senal(t, "52s", "max", "nuevo máximo de 52 semanas",
                        f"cerró en {_p(cierre)}, por encima del máximo del último año ({_p(r52['maximo'])}). "
                        f"Es un nivel que mira todo el mercado.", "alcista", 100, urgente=True))
    elif r52 and r52["nuevo_minimo"]:
        S.append(_senal(t, "52s", "min", "nuevo mínimo de 52 semanas",
                        f"cerró en {_p(cierre)}, por debajo del mínimo del último año ({_p(r52['minimo'])}). "
                        f"Perder ese piso suele traer más ventas.", "bajista", 100, urgente=True))

    # ── 2) Golden / death cross (urgente) ──
    if len(df) >= 202:
        e50, e200 = ema_tv(df["Close"], 50), ema_tv(df["Close"], 200)
        d_prev, d_act = float(e50.iloc[-2] - e200.iloc[-2]), float(e50.iloc[-1] - e200.iloc[-1])
        if d_prev <= 0 < d_act:
            S.append(_senal(t, "cruce_medias", "golden", "golden cross (EMA50 cruza sobre EMA200)",
                            "la media de 50 días cruzó por encima de la de 200: señal lenta pero de "
                            "cambio de tendencia de fondo a alcista.", "alcista", 95, urgente=True))
        elif d_prev >= 0 > d_act:
            S.append(_senal(t, "cruce_medias", "death", "death cross (EMA50 cruza bajo EMA200)",
                            "la media de 50 días cruzó por debajo de la de 200: señal lenta pero de "
                            "cambio de tendencia de fondo a bajista.", "bajista", 95, urgente=True))

    # ── 3) Movimiento fuerte (urgente) ──
    umbral = umbrales.get(tipo, 4)
    candidatos = [[(cierre / cierre_prev - 1) * 100, fecha, False]]   # [variación %, día, en curso]
    if intradia and len(df_todo) >= 2 and vela_en_curso(df_todo, "día"):
        var_hoy = (float(df_todo["Close"].iloc[-1]) / cierre - 1) * 100
        candidatos.append([var_hoy, df_todo.index[-1].date().isoformat(), True])
    for var, dia, en_curso in candidatos:
        if abs(var) >= umbral:
            sentido = "alza" if var > 0 else "baja"
            cuando = "hoy (vela en curso, datos con ~15 min de demora)" if en_curso else f"el {dia}"
            S.append(_senal(t, "movimiento", f"{sentido}|{dia}",
                            f"movimiento fuerte: {var:+.1f}% en el día" + (" (en curso)" if en_curso else ""),
                            f"se movió {var:+.1f}% {cuando}, más que el umbral de ±{umbral}% para este tipo "
                            f"de activo.", "alcista" if var > 0 else "bajista", 90, urgente=True,
                            en_curso=en_curso))

    # ── 4) Niveles de Fibonacci (calculados con las velas previas a la evaluada) ──
    fib_prev = calcular_fibonacci(prev, barras=TIMEFRAMES["diario"]["fib_barras"])
    niveles = {**fib_prev["niveles"], **fib_prev["extensiones"]}
    if niveles_fib is not None:
        niveles = {k: v for k, v in niveles.items() if k in niveles_fib or k.startswith("ext")}
    arriba = [(k, v) for k, v in niveles.items() if cierre_prev < v <= cierre]
    abajo = [(k, v) for k, v in niveles.items() if cierre_prev > v >= cierre]
    if arriba:
        k, v = max(arriba, key=lambda kv: kv[1])   # el nivel más alto que superó
        S.append(_senal(t, "fib_ruptura", k, f"rompe {_nombre_nivel(k)} al alza",
                        f"cerró en {_p(cierre)}, por encima de {_nombre_nivel(k)} ({_p(v)}). Si se sostiene, "
                        f"ese techo pasa a funcionar como soporte.", "alcista", 70))
    if abajo:
        k, v = min(abajo, key=lambda kv: kv[1])    # el nivel más bajo que perdió
        S.append(_senal(t, "fib_ruptura", k, f"pierde {_nombre_nivel(k)}",
                        f"cerró en {_p(cierre)}, por debajo de {_nombre_nivel(k)} ({_p(v)}). Ese piso pasa a "
                        f"funcionar como resistencia.", "bajista", 70))
    if not arriba and not abajo:
        # Toque: la vela llegó al nivel pero no lo cruzó al cierre, y la vela anterior no lo tocaba
        toques = [(k, v) for k, v in niveles.items()
                  if float(vela["Low"]) <= v <= float(vela["High"])
                  and not (float(vela_prev["Low"]) <= v <= float(vela_prev["High"]))]
        if toques:
            k, v = min(toques, key=lambda kv: abs(kv[1] - cierre))
            if v > cierre:
                S.append(_senal(t, "fib_toque", k, f"toca resistencia en {_nombre_nivel(k)}",
                                f"el precio llegó hasta {_nombre_nivel(k)} ({_p(v)}) y cerró debajo, en "
                                f"{_p(cierre)}: zona donde suele frenarse.", "neutral", 40))
            else:
                S.append(_senal(t, "fib_toque", k, f"toca soporte en {_nombre_nivel(k)}",
                                f"el precio bajó hasta {_nombre_nivel(k)} ({_p(v)}) y cerró arriba, en "
                                f"{_p(cierre)}: zona donde suele rebotar.", "neutral", 40))

    # ── 5) RSI cruza 30 o 70 ──
    rsi = serie_rsi(df)
    r0, r1 = float(rsi.iloc[-2]), float(rsi.iloc[-1])
    if r0 >= 30 > r1:
        S.append(_senal(t, "rsi", "entra_sobreventa", f"RSI entra en sobreventa ({r1:.0f})",
                        "el RSI cayó debajo de 30: está sobrevendido. Suele anticipar rebotes, pero "
                        "todavía puede seguir cayendo.", "bajista", 55))
    elif r0 < 30 <= r1:
        S.append(_senal(t, "rsi", "sale_sobreventa", f"RSI sale de sobreventa ({r1:.0f})",
                        "el RSI volvió arriba de 30: señal clásica de posible rebote.", "alcista", 55))
    elif r0 <= 70 < r1:
        S.append(_senal(t, "rsi", "entra_sobrecompra", f"RSI entra en sobrecompra ({r1:.0f})",
                        "el RSI superó 70: el impulso es fuerte, pero suele anticipar una pausa.",
                        "alcista", 55))
    elif r0 > 70 >= r1:
        S.append(_senal(t, "rsi", "sale_sobrecompra", f"RSI sale de sobrecompra ({r1:.0f})",
                        "el RSI volvió debajo de 70: señal clásica de que el impulso se agota.",
                        "bajista", 55))

    # ── 6) Cruce del MACD (solo si fue en esta vela) ──
    macd = calcular_macd(df, ventana_cruce=1)
    if macd.get("cruce") and macd.get("cruce_hace") == 0:
        alcista = macd["cruce"] == "alcista"
        zona = "debajo" if not macd["sobre_cero"] else "arriba"
        S.append(_senal(t, "macd", macd["cruce"], f"cruce {macd['cruce']} del MACD",
                        f"la línea MACD cruzó su señal hacia {'arriba' if alcista else 'abajo'} ({zona} de cero): "
                        f"el impulso gira a favor de la {'suba' if alcista else 'baja'}.",
                        "alcista" if alcista else "bajista", 60))

    # ── 7) Divergencia RSI nueva (aparece en esta vela) ──
    d_act, d_ant = detectar_divergencias(df), detectar_divergencias(prev)
    if d_act["alcista"] and not d_ant["alcista"]:
        S.append(_senal(t, "divergencia", "alcista", "divergencia alcista (candidata)",
                        "el precio marcó un mínimo más bajo pero el RSI no lo acompañó. Es una señal "
                        "CANDIDATA: confirmala en el gráfico.", "alcista", 50))
    if d_act["bajista"] and not d_ant["bajista"]:
        S.append(_senal(t, "divergencia", "bajista", "divergencia bajista (candidata)",
                        "el precio marcó un máximo más alto pero el RSI no lo acompañó. Es una señal "
                        "CANDIDATA: confirmala en el gráfico.", "bajista", 50))

    # ── Filtro anti-amague: volumen de la vela evaluada ──
    vol = calcular_volumen_relativo(df, "día")
    info["volumen_ratio"] = vol.get("ratio")
    if vol.get("ratio") is not None and vol["ratio"] < vol_minimo:
        for s in S:
            s["baja_conviccion"] = not s["en_curso"]   # la vela en curso tiene volumen parcial

    S.sort(key=lambda s: s["prioridad"], reverse=True)
    return S, info


def detectar_senales(activo, umbrales, vol_minimo=0.7, intradia=True, niveles_fib=None):
    """Descarga el diario del activo y le aplica las reglas."""
    df_todo = bajar_datos(activo["yf"], TIMEFRAMES["diario"]["period"], "1d")
    return evaluar_senales(df_todo, activo, umbrales, vol_minimo, intradia, niveles_fib)
