"""
tecnico.py — Análisis técnico del bot.

Calcula, para un ticker:
  - RSI (14) con contexto de zona (neutral / acercándose / sobreventa-sobrecompra)
  - Medias móviles (EMA20, EMA50, EMA200) y posición del precio
  - Niveles de Fibonacci trazados sobre el máximo/mínimo de los últimos 6 meses
  - Detección de divergencias (candidatas, para confirmar a ojo)

Fuente de datos: yfinance (gratis, sin API key).
Todo el análisis se calcula con datos actuales bajados al momento.
"""

import time
from functools import lru_cache

import yfinance as yf
import pandas as pd
import numpy as np


# ── Caché simple en memoria para no golpear a Yahoo de más (rate limit) ──
# Guarda cada descarga por un rato; así consultas repetidas y /revisar pesan mucho menos.
_CACHE = {}


def _cache_get(key, ttl):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_set(key, valor):
    _CACHE[key] = (time.time(), valor)


# Símbolos de cripto conocidos. En yfinance cotizan como "BTC-USD", no "BTC".
# Si el usuario escribe /btc, hay que traducirlo o el bot baja OTRO activo
# (existe una acción "BTC" que cotiza a ~$28 y no tiene nada que ver con Bitcoin).
CRIPTOS = {
    "BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "BNB", "DOT", "AVAX",
    "MATIC", "POL", "LTC", "LINK", "SHIB", "TRX", "ATOM", "UNI", "ETC",
    "XLM", "BCH", "NEAR", "APT", "ARB", "OP", "FIL", "ICP",
}


@lru_cache(maxsize=1)
def alias_alertas():
    """
    Tickers de la watchlist de alertas (config.ALERTAS_ACTIVOS) por nombre corto, para que
    /HSI, /ORO o /US10Y en el bot vayan al símbolo correcto de Yahoo (^HSI, GC=F, ^TNX).
    """
    try:
        from config.config import ALERTAS_ACTIVOS
    except Exception:
        return {}
    return {a["ticker"].upper(): a for a in ALERTAS_ACTIVOS}


def normalizar_ticker(ticker):
    """
    Devuelve (ticker_yfinance, es_cripto).

    - Ticker de la watchlist de alertas con símbolo distinto en Yahoo (HSI -> ^HSI, ORO -> GC=F).
    - Cripto conocida (BTC, ETH, ...) -> le agrega '-USD' para que yfinance
      baje la cotización real en dólares.
    - Si ya viene con '-USD' (ej: BTC-USD), se respeta y se marca como cripto.
    - Cualquier otro ticker (acciones) se deja igual.
    """
    t = ticker.strip().upper()
    alias = alias_alertas().get(t)
    if alias and alias["yf"].upper() != t:
        return alias["yf"], alias["tipo"] == "cripto"
    if t.endswith("-USD"):
        return t, True
    if t in CRIPTOS:
        return f"{t}-USD", True
    return t, False


# Horizontes disponibles. "diario" es el default (comportamiento histórico del bot).
# "period" es cuánto historial se baja: tiene que alcanzar para que la EMA200 converja
# y dé igual que en TradingView (con 1 año de diario quedaba ~1% corrida). Fibonacci,
# divergencias, volumen y fase usan solo las últimas N velas, así que no cambian.
# "4h" no existe en yfinance: se arma agrupando velas de 1h ("resample"). 1h y 4h usan
# la misma descarga (720 días, el máximo que da Yahoo para intradía), que queda en caché.
TIMEFRAMES = {
    "diario":  {"period": "5y",   "interval": "1d",  "fib_barras": 126, "nombre": "Diario (6 meses)", "unidad": "día"},
    "semanal": {"period": "max",  "interval": "1wk", "fib_barras": 52,  "nombre": "Semanal (1 año)", "unidad": "semana"},
    "4h":      {"period": "720d", "interval": "60m", "fib_barras": 90,  "nombre": "4 horas", "unidad": "vela de 4h",
                "resample": "4h"},
    "1h":      {"period": "720d", "interval": "60m", "fib_barras": 60,  "nombre": "Intradía 1h (~10 ruedas)", "unidad": "hora"},
}

# Alias que puede escribir el usuario en Telegram -> clave de TIMEFRAMES.
ALIAS_TIMEFRAME = {
    "diario": "diario", "1d": "diario", "d": "diario",
    "semanal": "semanal", "semana": "semanal", "1w": "semanal", "1wk": "semanal", "w": "semanal",
    "4h": "4h", "4hs": "4h", "4horas": "4h",
    "1h": "1h", "h": "1h", "hora": "1h", "intradia": "1h", "intradía": "1h",
}


def resolver_timeframe(valor):
    """
    Traduce lo que escribió el usuario (o None) a una config de TIMEFRAMES.
    Devuelve (clave, config) o lanza ValueError si no se reconoce.
    """
    if not valor:
        clave = "diario"
    else:
        clave = ALIAS_TIMEFRAME.get(valor.strip().lower())
        if clave is None:
            opciones = ", ".join(sorted(set(ALIAS_TIMEFRAME.values())))
            raise ValueError(f"Horizonte '{valor}' no reconocido. Usá: {opciones}")
    return clave, TIMEFRAMES[clave]


def bajar_datos(ticker, periodo="1y", intervalo="1d"):
    """
    Baja el histórico de precios según el período/intervalo pedido.

    auto_adjust=False a propósito: yfinance por default ajusta Open/High/Low/Close
    por DIVIDENDOS además de splits, lo que "achica" precios históricos reales
    (ej: YPF mostraba un máximo histórico de hace meses en vez del real de 2005,
    por 20 años de dividendos acumulados). Con auto_adjust=False se mantienen
    los precios tal como se operaron (solo ajustados por splits), que es lo que
    hace falta para niveles técnicos (soportes, resistencias, máximos) reales.

    Además usa caché y reintentos para sobrevivir al rate limit de Yahoo, frecuente
    desde IPs de datacenter (como la de Render).
    """
    key = ("hist", ticker, periodo, intervalo)
    # El histórico completo ("max") cambia poco -> se cachea más tiempo.
    ttl = 3600 if periodo == "max" else 600
    cacheado = _cache_get(key, ttl)
    if cacheado is not None:
        return cacheado

    ultimo_error = None
    for i in range(3):
        try:
            df = yf.Ticker(ticker).history(period=periodo, interval=intervalo, auto_adjust=False)
            if not df.empty:
                _cache_set(key, df)
                return df
            ultimo_error = ValueError(f"No se pudieron bajar datos de {ticker}")
        except Exception as e:
            ultimo_error = e
        if i < 2:
            time.sleep(1.0 * (i + 1))  # espera creciente entre reintentos

    raise ultimo_error if ultimo_error else ValueError(f"No se pudieron bajar datos de {ticker}")


def serie_rsi(df, periodo=14):
    """Serie completa del RSI clásico de Wilder (sirve para detectar cruces de 30/70)."""
    delta = df["Close"].diff()
    ganancia = delta.where(delta > 0, 0.0)
    perdida = -delta.where(delta < 0, 0.0)
    # Media exponencial de Wilder (alpha = 1/periodo)
    avg_gan = ganancia.ewm(alpha=1/periodo, adjust=False).mean()
    avg_per = perdida.ewm(alpha=1/periodo, adjust=False).mean()
    rs = avg_gan / avg_per
    return 100 - (100 / (1 + rs))


def calcular_rsi(df, periodo=14):
    """RSI clásico de Wilder. Devuelve el valor actual redondeado."""
    return round(float(serie_rsi(df, periodo).iloc[-1]), 1)


def contexto_rsi(rsi):
    """
    Traduce el número de RSI a una lectura en criollo con zona.
    Umbrales clásicos 30/70, pero avisa cuando se está acercando.
    """
    if rsi < 30:
        estado = "sobreventa"
        texto = f"RSI {round(rsi)} — sobrevendido, suele preceder rebotes (pero puede seguir cayendo)."
    elif rsi < 40:
        estado = "acercandose_sobreventa"
        texto = f"RSI {round(rsi)} — acercándose a sobreventa, atento a un posible piso."
    elif rsi <= 60:
        estado = "neutral"
        texto = f"RSI {round(rsi)} — zona neutral, sin señal de extremo."
    elif rsi <= 70:
        estado = "acercandose_sobrecompra"
        texto = f"RSI {round(rsi)} — acercándose a sobrecompra, el impulso puede estar agotándose."
    else:
        estado = "sobrecompra"
        texto = f"RSI {round(rsi)} — sobrecomprado, puede venir una corrección (pero puede seguir subiendo)."
    return {"valor": rsi, "estado": estado, "texto": texto}


def ema_tv(serie, n):
    """
    EMA calculada EXACTAMENTE como TradingView (ta.ema de Pine Script): arranca con la
    SMA de las primeras n velas y después aplica la fórmula recursiva (alpha = 2/(n+1)).
    La ewm de pandas arranca desde la primera vela y, con poco historial, la EMA200
    quedaba ~1% distinta de la que ves en TradingView.

    Tolera valores vacíos al principio (ej: la línea de señal del MACD es una EMA del
    MACD, que arranca vacío): la SMA inicial se toma desde el primer valor válido.
    """
    vals = serie.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    validos = np.flatnonzero(~np.isnan(vals))
    if len(validos) == 0:
        return pd.Series(out, index=serie.index)
    inicio = validos[0]
    semilla = inicio + n - 1
    if semilla < len(vals):
        alpha = 2 / (n + 1)
        out[semilla] = np.nanmean(vals[inicio:semilla + 1])
        for i in range(semilla + 1, len(vals)):
            v = vals[i]
            out[i] = out[i - 1] if np.isnan(v) else alpha * v + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=serie.index)


def _pendiente(serie_ema, velas=5, umbral=0.05):
    """Hacia dónde apunta una media: % de cambio en las últimas 'velas' (subiendo/bajando/plana)."""
    s = serie_ema.dropna()
    if len(s) <= velas:
        return {"pct": None, "direccion": "indefinida"}
    pct = (float(s.iloc[-1]) / float(s.iloc[-1 - velas]) - 1) * 100
    direccion = "subiendo" if pct > umbral else ("bajando" if pct < -umbral else "plana")
    return {"pct": round(pct, 2), "direccion": direccion}


def calcular_medias(df):
    """EMA 20/50/200, posición del precio respecto a ellas y pendiente de cada una."""
    precio = float(df["Close"].iloc[-1])
    series = {n: ema_tv(df["Close"], n) for n in (20, 50, 200)}
    ema20 = float(series[20].iloc[-1])
    ema50 = float(series[50].iloc[-1])
    ema200 = float(series[200].iloc[-1])

    sobre = [n for n, e in [("EMA20", ema20), ("EMA50", ema50), ("EMA200", ema200)] if precio >= e]
    bajo = [n for n, e in [("EMA20", ema20), ("EMA50", ema50), ("EMA200", ema200)] if precio < e]

    # Lectura simple de tendencia según cuántas medias tiene por encima
    if len(sobre) == 3:
        texto = "Precio por encima de todas las medias — tendencia alcista sana."
    elif len(sobre) == 0:
        texto = "Precio por debajo de todas las medias — tendencia bajista."
    else:
        texto = f"Precio sobre {', '.join(sobre)} y bajo {', '.join(bajo)} — señal mixta."

    return {
        "precio": round(precio, 2),
        "ema20": round(ema20, 2), "ema50": round(ema50, 2), "ema200": round(ema200, 2),
        "pendientes": {f"ema{n}": _pendiente(s) for n, s in series.items()},
        "texto": texto,
    }


def calcular_fibonacci(df, barras=126):
    """
    Traza los retrocesos de Fibonacci sobre el máximo y mínimo de las últimas N barras
    (velas). El significado de "barras" depende del timeframe (días, semanas u horas).
    Indica entre qué dos niveles está el precio y cuál es el soporte/resistencia más cercano.
    """
    reciente = df.tail(barras)
    maximo = float(reciente["High"].max())
    minimo = float(reciente["Low"].min())
    rango = maximo - minimo
    precio = float(df["Close"].iloc[-1])

    niveles = {
        "0.0 (máx)": maximo,
        "0.236": maximo - 0.236 * rango,
        "0.382": maximo - 0.382 * rango,
        "0.5": maximo - 0.5 * rango,
        "0.618": maximo - 0.618 * rango,
        "0.786": maximo - 0.786 * rango,
        "1.0 (mín)": minimo,
    }

    # Extensiones: próximos objetivos si el precio sale del rango por arriba o por abajo.
    extensiones = {
        "ext 1.272": maximo + 0.272 * rango,
        "ext 1.618": maximo + 0.618 * rango,
        "ext 1.272↓": minimo - 0.272 * rango,
        "ext 1.618↓": minimo - 0.618 * rango,
    }
    extensiones = {k: v for k, v in extensiones.items() if v > 0}

    def nombre_de(valor):
        return min(niveles.items(), key=lambda kv: abs(kv[1] - valor))[0]

    # Nivel de soporte (el más cercano por debajo) y resistencia (el más cercano por encima).
    # Si el precio está en el máximo del rango (rompiendo), el techo ya no es ese máximo
    # sino la extensión 1.272; igual con el mínimo hacia abajo.
    if rango > 0 and precio >= maximo * 0.997 and "ext 1.272" in extensiones:
        resistencia, res_nombre = extensiones["ext 1.272"], "ext 1.272"
    else:
        resistencia = min([v for v in niveles.values() if v >= precio], default=maximo)
        res_nombre = nombre_de(resistencia)
    if rango > 0 and precio <= minimo * 1.003 and "ext 1.272↓" in extensiones:
        soporte, sop_nombre = extensiones["ext 1.272↓"], "ext 1.272↓"
    else:
        soporte = max([v for v in niveles.values() if v <= precio], default=minimo)
        sop_nombre = nombre_de(soporte)

    return {
        "maximo": round(maximo, 2), "minimo": round(minimo, 2),
        "niveles": {k: round(v, 2) for k, v in niveles.items()},
        "extensiones": {k: round(v, 2) for k, v in extensiones.items()},
        "soporte": round(soporte, 2), "soporte_nombre": sop_nombre,
        "resistencia": round(resistencia, 2), "resistencia_nombre": res_nombre,
        "texto": f"Entre {sop_nombre} (${round(soporte,2)}) y "
                 f"{res_nombre} (${round(resistencia,2)}).",
    }


def detectar_divergencias(df, periodo_rsi=14, ventana=60, orden=5):
    """
    Detecta divergencias CANDIDATAS entre precio y RSI en las últimas 'ventana' ruedas.
    - Alcista: precio hace mínimo más bajo, RSI hace mínimo más alto.
    - Bajista: precio hace máximo más alto, RSI hace máximo más bajo.

    OJO: la detección automática tiene falsos positivos. El bot la marca como
    CANDIDATA para que la confirmes mirando el gráfico. No es una señal cerrada.
    """
    delta = df["Close"].diff()
    g = delta.where(delta > 0, 0.0).ewm(alpha=1/periodo_rsi, adjust=False).mean()
    p = -delta.where(delta < 0, 0.0).ewm(alpha=1/periodo_rsi, adjust=False).mean()
    rsi_serie = 100 - (100 / (1 + g / p))

    sub = df.tail(ventana).copy()
    rsi_sub = rsi_serie.tail(ventana).reset_index(drop=True)
    precio = sub["Close"].reset_index(drop=True)

    def pivotes_min(serie):
        idx = []
        for i in range(orden, len(serie) - orden):
            if serie[i] == min(serie[i-orden:i+orden+1]):
                idx.append(i)
        return idx

    def pivotes_max(serie):
        idx = []
        for i in range(orden, len(serie) - orden):
            if serie[i] == max(serie[i-orden:i+orden+1]):
                idx.append(i)
        return idx

    resultado = {"alcista": False, "bajista": False, "texto": "Sin divergencias candidatas."}

    min_precio = pivotes_min(precio)
    if len(min_precio) >= 2:
        a, b = min_precio[-2], min_precio[-1]
        if precio[b] < precio[a] and rsi_sub[b] > rsi_sub[a]:
            resultado["alcista"] = True
            resultado["texto"] = ("Posible divergencia ALCISTA (precio marca mínimo más bajo pero "
                                  "el RSI no lo acompaña). CANDIDATA — confirmá en el gráfico.")

    max_precio = pivotes_max(precio)
    if len(max_precio) >= 2:
        a, b = max_precio[-2], max_precio[-1]
        if precio[b] > precio[a] and rsi_sub[b] < rsi_sub[a]:
            resultado["bajista"] = True
            resultado["texto"] = ("Posible divergencia BAJISTA (precio marca máximo más alto pero "
                                  "el RSI no lo acompaña). CANDIDATA — confirmá en el gráfico.")

    return resultado


def vela_en_curso(df, unidad):
    """
    ¿La última vela todavía se está formando? (su período no terminó).
    Las alertas se evalúan solo sobre velas cerradas: una vela en curso cambia
    hasta el cierre y puede dar señales falsas (ej: el "0.0x" de volumen).
    """
    idx = df.index
    ahora = pd.Timestamp.now(tz=idx.tz) if getattr(idx, "tz", None) is not None else pd.Timestamp.now()
    ult = idx[-1]
    if unidad == "día":
        return ult.date() == ahora.date()
    if unidad == "semana":
        return ult.strftime("%G-%V") == ahora.strftime("%G-%V")
    if unidad == "hora":
        return ult.floor("h") == ahora.floor("h")
    if unidad == "vela de 4h":
        return ahora < ult + pd.Timedelta(hours=4)
    return False


def solo_velas_cerradas(df, unidad):
    """Devuelve el DataFrame sin la última vela si todavía está en curso."""
    return df.iloc[:-1] if len(df) > 1 and vela_en_curso(df, unidad) else df


def calcular_volumen_relativo(df, unidad="día", ventana=20):
    """
    Volumen de la última vela COMPLETA comparado con el promedio de las anteriores.

    NO es una señal de compra/venta: es un CONFIRMADOR. Un movimiento con volumen alto
    tiene fuerza real detrás; con volumen flojo suele ser un amague.

    OJO: la última vela puede estar EN CURSO (volumen parcial). Ej: si corrés el bot
    antes de que abra el mercado, la vela del día tiene volumen ~0 y daría un falso
    "0.0x". Por eso, si la última vela es del período actual (o tiene volumen 0), la
    descartamos y usamos la última vela completa. El promedio también la excluye.
    """
    vols = df["Volume"].dropna()
    if len(vols) < ventana + 2:
        return {"ratio": None, "estado": "sin_datos",
                "texto": "Volumen no disponible para este activo."}

    if vela_en_curso(df, unidad) or float(vols.iloc[-1]) == 0:
        vols = vols.iloc[:-1]   # descartar la vela en curso / vacía

    if len(vols) < ventana + 1:
        return {"ratio": None, "estado": "sin_datos",
                "texto": "Volumen no disponible para este activo."}

    actual = float(vols.iloc[-1])                          # última vela COMPLETA
    promedio = float(vols.iloc[-(ventana + 1):-1].mean())  # promedio de las anteriores (sin la actual)
    if promedio <= 0:
        return {"ratio": None, "estado": "sin_datos",
                "texto": "Volumen no disponible para este activo."}

    ratio = actual / promedio
    if ratio >= 1.5:
        estado = "alto"
        texto = (f"🔊 Volumen {ratio:.1f}x su promedio — hay fuerza real detrás del "
                 f"movimiento, la señal técnica pesa más.")
    elif ratio <= 0.6:
        estado = "bajo"
        texto = (f"🔈 Volumen {ratio:.1f}x su promedio — poco interés hoy, conviene "
                 f"tomar la señal con pinzas (puede ser un amague).")
    else:
        estado = "normal"
        texto = f"🔉 Volumen {ratio:.1f}x su promedio — participación normal."
    return {"ratio": round(ratio, 2), "estado": estado, "texto": texto}


# Cercanía (en %) para considerar que el precio está "pegado" a un nivel de Fibonacci.
UMBRAL_FIB = 0.015  # 1.5%


def semaforo_tecnico(precio, rsi_ctx, medias, fibonacci, divergencias, volumen=None):
    """
    Semáforo técnico MULTIFACTOR y graduado.

    Combina 4 factores que el bot ya calcula, cada uno vota compra (+) / venta (-) /
    neutral (0). El RSI en extremo (sobreventa/sobrecompra) pesa doble porque es la
    señal más fuerte. La suma define el color y la intensidad, y se muestra cuántos
    factores están de acuerdo para que la lectura sea transparente.

    Factores:
      1. RSI          — sobreventa +2 / acercándose +1 / neutral 0 / acercándose -1 / sobrecompra -2
      2. Fibonacci    — pegado a soporte +1 / pegado a resistencia -1 / lejos 0
      3. Medias (EMA) — precio sobre las 3 +1 / bajo las 3 -1 / mixto 0
      4. Divergencia  — alcista +1 / bajista -1 / ninguna 0
    """
    # ── Factor 1: RSI ──
    rsi_signo = {
        "sobreventa": 2, "acercandose_sobreventa": 1, "neutral": 0,
        "acercandose_sobrecompra": -1, "sobrecompra": -2,
    }[rsi_ctx["estado"]]

    # ── Factor 2: cercanía a soporte/resistencia de Fibonacci ──
    sop, res = fibonacci["soporte"], fibonacci["resistencia"]
    dist_sop = (precio - sop) / precio if precio else 1.0
    dist_res = (res - precio) / precio if precio else 1.0
    if dist_sop <= UMBRAL_FIB and dist_sop <= dist_res:
        fib_signo = 1
        fib_txt = f"pegado a soporte Fibonacci {fibonacci['soporte_nombre']} (${sop})"
    elif dist_res <= UMBRAL_FIB:
        fib_signo = -1
        fib_txt = f"pegado a resistencia Fibonacci {fibonacci['resistencia_nombre']} (${res})"
    else:
        fib_signo = 0
        fib_txt = "lejos de soportes/resistencias Fibonacci"

    # ── Factor 3: posición vs medias ──
    n_sobre = sum(precio >= medias[e] for e in ("ema20", "ema50", "ema200"))
    if n_sobre == 3:
        med_signo, med_txt = 1, "sobre las 3 medias (tendencia alcista)"
    elif n_sobre == 0:
        med_signo, med_txt = -1, "bajo las 3 medias (tendencia bajista)"
    else:
        med_signo, med_txt = 0, "posición mixta respecto a las medias"

    # ── Factor 4: divergencias ──
    if divergencias["alcista"]:
        div_signo, div_txt = 1, "divergencia alcista candidata"
    elif divergencias["bajista"]:
        div_signo, div_txt = -1, "divergencia bajista candidata"
    else:
        div_signo, div_txt = 0, "sin divergencias"

    signos = [rsi_signo, fib_signo, med_signo, div_signo]
    net = sum(signos)

    # Cuántos factores (de 4) apuntan en la dirección neta
    if net > 0:
        n_acuerdo = sum(1 for s in signos if s > 0)
    elif net < 0:
        n_acuerdo = sum(1 for s in signos if s < 0)
    else:
        n_acuerdo = 0

    # Tres niveles de intensidad por lado, framado como acción (comprar/vender/esperar).
    if net >= 3:
        color, accion, nivel = "verde", "COMPRAR", "señal fuerte"
    elif net == 2:
        color, accion, nivel = "verde", "COMPRAR", "señal moderada"
    elif net == 1:
        color, accion, nivel = "verde", "Comprar", "señal leve"
    elif net <= -3:
        color, accion, nivel = "rojo", "VENDER", "señal fuerte"
    elif net == -2:
        color, accion, nivel = "rojo", "VENDER", "señal moderada"
    elif net == -1:
        color, accion, nivel = "rojo", "Vender", "señal leve"
    else:
        # net == 0: distinguir "todo plano" de "señales que se cancelan"
        hay_opuestos = any(s > 0 for s in signos) and any(s < 0 for s in signos)
        color, accion = "amarillo", "ESPERAR"
        nivel = "señales mixtas" if hay_opuestos else "sin señal clara"

    titulo = f"{accion} — {nivel}"

    return {
        "color": color,
        "titulo": titulo,
        "accion": accion,
        "nivel": nivel,
        "net": net,
        "n_acuerdo": n_acuerdo,
        "factores": {
            "rsi": {"signo": rsi_signo, "texto": rsi_ctx["texto"]},
            "fibonacci": {"signo": fib_signo, "texto": fib_txt},
            "medias": {"signo": med_signo, "texto": med_txt},
            "divergencia": {"signo": div_signo, "texto": div_txt},
        },
    }


def distancia_maximo_historico(df_diario):
    """
    Compara el precio actual contra el máximo histórico (todo el historial diario),
    a partir de un DataFrame diario ya bajado.
    """
    ath = float(df_diario["High"].max())
    precio = float(df_diario["Close"].iloc[-1])
    desvio = (precio - ath) / ath * 100  # <= 0

    if desvio >= -0.5:
        texto = f"🔝 En máximos históricos (${round(ath, 2)})."
    elif desvio >= -10:
        texto = f"A un {abs(round(desvio, 1))}% de su máximo histórico (${round(ath, 2)})."
    else:
        texto = f"En una caída del {abs(round(desvio, 1))}% desde su máximo histórico (${round(ath, 2)})."

    return {"ath": round(ath, 2), "desvio_pct": round(desvio, 1), "texto": texto}


def calcular_atr(df, periodo=14):
    """
    ATR (Average True Range): cuánto se mueve el activo por vela, en $ y en %.
    Sirve para calibrar stops: ni tan pegados que te barran, ni tan lejos que arriesgues de más.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / periodo, adjust=False).mean().iloc[-1])
    precio = float(close.iloc[-1])
    pct = atr / precio * 100 if precio else 0.0
    return {"atr": round(atr, 2), "pct": round(pct, 1)}


def _rb_direccion(gana, arriesga):
    """
    Clasifica un R:B a partir del % a ganar y del % a arriesgar.
    Devuelve (tipo, ratio). tipo: favorable / neutro / malo / sin_recorrido / pegado.
    """
    if gana < 0.2:
        return "sin_recorrido", None   # el objetivo está pegado (casi no hay para ganar)
    if arriesga < 0.2:
        return "pegado", None          # el stop está pegado (casi no hay para arriesgar)
    ratio = gana / arriesga
    if ratio >= 1.5:
        tipo = "favorable"
    elif ratio >= 1:
        tipo = "neutro"
    else:
        tipo = "malo"
    return tipo, round(ratio, 1)


def calcular_escenarios(precio, fibonacci, net):
    """
    Analiza los DOS escenarios de trade (long y short) usando los niveles de Fibonacci,
    e indica cuál es el más probable según el sesgo del semáforo técnico (net).

    - LONG (comprar): objetivo = resistencia (subís), stop = soporte (bajás).
    - SHORT (vender en corto): objetivo = soporte (baja), stop = resistencia (sube).
    El R:B de uno es el inverso del otro: los niveles favorecen a una sola dirección.
    """
    res, sop = fibonacci["resistencia"], fibonacci["soporte"]
    subida = (res - precio) / precio * 100   # % hasta la resistencia
    bajada = (precio - sop) / precio * 100    # % hasta el soporte

    long_tipo, long_ratio = _rb_direccion(subida, bajada)
    short_tipo, short_ratio = _rb_direccion(bajada, subida)

    if net > 0:
        favorito = "long"
    elif net < 0:
        favorito = "short"
    else:
        favorito = "ninguno"

    return {
        "resistencia": res, "soporte": sop,
        "subida_pct": round(subida, 1), "bajada_pct": round(bajada, 1),
        "long": {"tipo": long_tipo, "ratio": long_ratio},
        "short": {"tipo": short_tipo, "ratio": short_ratio},
        "favorito": favorito,
    }


def calcular_variacion_plazos(df_diario):
    """% de cambio en 1 día, 1 semana (~5 ruedas) y 1 mes (~21 ruedas), sobre datos diarios."""
    close = df_diario["Close"]
    precio = float(close.iloc[-1])

    def cambio(n):
        if len(close) > n:
            ref = float(close.iloc[-1 - n])
            if ref:
                return round((precio - ref) / ref * 100, 1)
        return None

    return {"1d": cambio(1), "1sem": cambio(5), "1mes": cambio(21)}


def detectar_cruce_medias(df, rapida=50, lenta=200, ventana=10):
    """
    Detecta un cruce reciente (últimas 'ventana' velas) de la media rápida sobre la lenta:
      - golden cross (rápida cruza HACIA ARRIBA de la lenta) = sesgo alcista de fondo.
      - death cross  (rápida cruza HACIA ABAJO) = sesgo bajista de fondo.
    Señal lenta, de tendencia mayor. Devuelve None si no hubo cruce reciente.
    """
    if len(df) < lenta + ventana:
        return {"cruce": None, "texto": None}
    ema_r = ema_tv(df["Close"], rapida)
    ema_l = ema_tv(df["Close"], lenta)
    signo = (ema_r - ema_l).dropna().apply(lambda x: 1 if x >= 0 else -1)
    reciente = signo.tail(ventana + 1).tolist()

    cruce = None
    for i in range(1, len(reciente)):
        if reciente[i - 1] < 0 and reciente[i] > 0:
            cruce = "golden"
        elif reciente[i - 1] > 0 and reciente[i] < 0:
            cruce = "death"

    if cruce == "golden":
        texto = "⚡ Golden cross reciente (EMA50 sobre EMA200) — sesgo alcista de fondo."
    elif cruce == "death":
        texto = "⚡ Death cross reciente (EMA50 bajo EMA200) — sesgo bajista de fondo."
    else:
        texto = None
    return {"cruce": cruce, "texto": texto}


def a_4h(df_1h, es_cripto):
    """
    Arma velas de 4 horas agrupando velas de 1h, alineadas como TradingView:
      - Mercados de 24 h (cripto, y futuros/dólar que operan casi todo el día):
        bloques de reloj desde las 00:00 UTC (00-04, 04-08, ...).
      - Acciones e índices: bloques desde la apertura de cada rueda
        (09:30-13:30 y 13:30-16:00 en EE.UU.).
    """
    agregacion = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    agregacion = {c: f for c, f in agregacion.items() if c in df_1h.columns}
    velas_por_dia = df_1h.groupby(df_1h.index.date).size().median() if len(df_1h) else 0
    if es_cripto or velas_por_dia > 8:
        d = df_1h.tz_convert("UTC") if df_1h.index.tz is not None else df_1h.tz_localize("UTC")
        velas = d.resample("4h", origin="start_day").agg(agregacion)
    else:
        fechas = df_1h.index.date
        bloque = df_1h.groupby(fechas).cumcount().to_numpy() // 4
        inicio = pd.Series(df_1h.index, index=df_1h.index).groupby([fechas, bloque]).transform("first")
        velas = df_1h.groupby(pd.DatetimeIndex(inicio)).agg(agregacion)
    return velas.dropna(subset=["Close"])


def calcular_macd(df, rapida=12, lenta=26, senal=9, ventana_cruce=3):
    """
    MACD (12, 26, 9) calculado como TradingView: línea MACD = EMA12 − EMA26, señal = EMA9
    del MACD, histograma = MACD − señal. Detecta si hubo cruce en las últimas velas.
    """
    close = df["Close"]
    macd = ema_tv(close, rapida) - ema_tv(close, lenta)
    senal_s = ema_tv(macd, senal)
    hist = macd - senal_s
    if hist.dropna().empty:
        return {"macd": None, "senal": None, "hist": None, "cruce": None, "texto": "MACD sin datos suficientes."}

    m, s = float(macd.iloc[-1]), float(senal_s.iloc[-1])
    h = hist.dropna()
    h_act, h_prev = float(h.iloc[-1]), float(h.iloc[-2]) if len(h) > 1 else float(h.iloc[-1])

    # Cruce de la línea MACD con su señal en las últimas 'ventana_cruce' velas
    signo = np.sign(h.tail(ventana_cruce + 1).to_numpy())
    cruce, hace = None, None
    for i in range(1, len(signo)):
        if signo[i - 1] <= 0 < signo[i]:
            cruce, hace = "alcista", len(signo) - 1 - i
        elif signo[i - 1] >= 0 > signo[i]:
            cruce, hace = "bajista", len(signo) - 1 - i

    impulso = "ganando fuerza" if abs(h_act) > abs(h_prev) else "perdiendo fuerza"
    if cruce:
        cuando = "en la última vela" if hace == 0 else f"hace {hace} vela{'s' if hace > 1 else ''}"
        texto = (f"MACD: cruce {cruce} {cuando} (la línea MACD cruzó su señal "
                 f"{'hacia arriba' if cruce == 'alcista' else 'hacia abajo'}).")
    else:
        texto = (f"MACD {'positivo' if m > s else 'negativo'} ({'sobre' if m > s else 'bajo'} su señal, "
                 f"{'sobre' if m > 0 else 'bajo'} cero) — impulso {impulso}.")
    return {"macd": round(m, 4), "senal": round(s, 4), "hist": round(h_act, 4),
            "positivo": m > s, "sobre_cero": m > 0, "impulso": impulso,
            "cruce": cruce, "cruce_hace": hace, "texto": texto}


def calcular_obv(df, ventana=20):
    """
    OBV (On-Balance Volume): suma el volumen de las velas que suben y resta el de las que
    bajan. Si el OBV acompaña al precio, el volumen confirma la tendencia; si va en contra,
    el movimiento no tiene respaldo.
    """
    close, vol = df["Close"], df["Volume"].fillna(0)
    obv = (np.sign(close.diff()).fillna(0) * vol).cumsum()
    if len(obv) <= ventana:
        return {"tendencia": "indefinida", "confirma": None, "texto": "OBV sin datos suficientes."}

    cambio_obv = float(obv.iloc[-1] - obv.iloc[-1 - ventana])
    cambio_precio = float(close.iloc[-1] - close.iloc[-1 - ventana])
    volumen_ventana = float(vol.tail(ventana).sum()) or 1.0
    if abs(cambio_obv) < 0.1 * volumen_ventana:
        tend_obv = "plano"
    else:
        tend_obv = "sube" if cambio_obv > 0 else "baja"
    tend_precio = "sube" if cambio_precio > 0 else "baja"

    if tend_obv == "plano":
        confirma, texto = None, "OBV plano — el volumen no se inclina para ningún lado."
    elif tend_obv == tend_precio:
        confirma = True
        texto = f"OBV {tend_obv} junto con el precio — el volumen confirma la tendencia."
    else:
        confirma = False
        texto = (f"OBV {tend_obv} mientras el precio {tend_precio} — el movimiento no tiene "
                 f"respaldo de volumen (ojo).")
    return {"tendencia": tend_obv, "confirma": confirma, "texto": texto}


def _pivotes(valores, orden, tipo):
    """Índices de máximos (tipo='max') o mínimos (tipo='min') locales con 'orden' velas a cada lado."""
    idx = []
    for i in range(orden, len(valores) - orden):
        ventana = valores[i - orden:i + orden + 1]
        if (tipo == "max" and valores[i] == ventana.max()) or (tipo == "min" and valores[i] == ventana.min()):
            idx.append(i)
    return idx


def detectar_estructura(df, ventana=120, orden=5):
    """
    Estructura de máximos y mínimos (los dos últimos swings):
      - HH/HL (máximos y mínimos más altos) = tendencia alcista.
      - LH/LL (máximos y mínimos más bajos) = tendencia bajista.
      - Mixta = lateral / en transición.
    """
    sub = df.tail(ventana)
    highs, lows = sub["High"].to_numpy(dtype=float), sub["Low"].to_numpy(dtype=float)
    ph, pl = _pivotes(highs, orden, "max"), _pivotes(lows, orden, "min")
    if len(ph) < 2 or len(pl) < 2:
        return {"tipo": "indefinida", "texto": "Estructura sin swings suficientes para leerla."}

    h1, h2 = highs[ph[-2]], highs[ph[-1]]
    l1, l2 = lows[pl[-2]], lows[pl[-1]]
    hh, hl = h2 > h1, l2 > l1
    if hh and hl:
        tipo, texto = "alcista", "Máximos y mínimos cada vez más altos (HH/HL) — estructura alcista."
    elif not hh and not hl:
        tipo, texto = "bajista", "Máximos y mínimos cada vez más bajos (LH/LL) — estructura bajista."
    elif hh and not hl:
        tipo, texto = "lateral", "Máximo más alto pero mínimo más bajo — rango que se abre (volatilidad)."
    else:
        tipo, texto = "lateral", "Máximo más bajo y mínimo más alto — rango que se comprime (define pronto)."
    return {"tipo": tipo, "texto": texto,
            "maximos": (round(h1, 2), round(h2, 2)), "minimos": (round(l1, 2), round(l2, 2))}


def calcular_roc(df, periodo=10):
    """Rate of Change: % de variación contra el cierre de hace 'periodo' velas."""
    close = df["Close"]
    if len(close) <= periodo:
        return None
    return round((float(close.iloc[-1]) / float(close.iloc[-1 - periodo]) - 1) * 100, 2)


def rango_52_semanas(df_diario):
    """
    Máximo y mínimo de las 52 semanas previas (sin contar la última vela) y dónde está el
    precio. Si el cierre supera ese máximo (o perfora el mínimo), es un nuevo récord anual.
    """
    if len(df_diario) < 30:
        return None
    previo = df_diario.iloc[:-1].tail(252)
    maximo, minimo = float(previo["High"].max()), float(previo["Low"].min())
    precio = float(df_diario["Close"].iloc[-1])
    return {
        "maximo": round(maximo, 2), "minimo": round(minimo, 2),
        "dist_max_pct": round((precio - maximo) / maximo * 100, 1),
        "dist_min_pct": round((precio - minimo) / minimo * 100, 1),
        "nuevo_maximo": precio > maximo, "nuevo_minimo": precio < minimo,
    }


def detectar_fase(df, ventana=30):
    """
    Detecta la FASE reciente del precio en las últimas 'ventana' velas:
      - "bajando": viene en caída (cuidado con acumular, "cuchillo cayendo").
      - "lateral": se estabilizó / lateraliza (dejó de caer; mejor zona para acumular de a poco).
      - "subiendo": viene recuperando.
    Se mide con el cambio neto punta a punta y el ancho del rango.
    """
    reciente = df["Close"].tail(ventana)
    if len(reciente) < 5:
        return {"fase": "indefinida", "cambio_pct": None}
    ini, fin = float(reciente.iloc[0]), float(reciente.iloc[-1])
    cambio = (fin - ini) / ini * 100 if ini else 0.0

    if cambio <= -8:
        fase = "bajando"
    elif cambio >= 8:
        fase = "subiendo"
    else:
        fase = "lateral"
    return {"fase": fase, "cambio_pct": round(cambio, 1)}


def analisis_tecnico_completo(ticker, timeframe=None, solo_cerradas=False):
    """
    Junta todo el análisis técnico de un ticker en un solo diccionario.
    solo_cerradas=True descarta la vela en curso (lo usan las alertas, que se evalúan
    sobre velas cerradas); el reporte de /TICKER usa el precio más reciente.
    """
    ticker_yf, es_cripto = normalizar_ticker(ticker)
    clave_tf, cfg = resolver_timeframe(timeframe)
    df = bajar_datos(ticker_yf, periodo=cfg["period"], intervalo=cfg["interval"])
    if cfg.get("resample") == "4h":
        df = a_4h(df, es_cripto)
    if solo_cerradas:
        df = solo_velas_cerradas(df, cfg["unidad"])
    rsi = calcular_rsi(df)
    precio = round(float(df["Close"].iloc[-1]), 2)
    rsi_ctx = contexto_rsi(rsi)
    medias = calcular_medias(df)
    fibonacci = calcular_fibonacci(df, barras=cfg["fib_barras"])
    divergencias = detectar_divergencias(df)
    volumen = calcular_volumen_relativo(df, cfg["unidad"])
    atr = calcular_atr(df)
    cruce = detectar_cruce_medias(df)

    # El semáforo define el sesgo (net); con eso se decide el escenario más probable.
    semaforo = semaforo_tecnico(precio, rsi_ctx, medias, fibonacci, divergencias, volumen)
    escenarios = calcular_escenarios(precio, fibonacci, semaforo["net"])

    # Datos diarios (todo el historial) una sola vez: sirven para ATH y para momentum.
    df_diario = bajar_datos(ticker_yf, periodo="max", intervalo="1d")
    if solo_cerradas:
        df_diario = solo_velas_cerradas(df_diario, "día")

    return {
        "ticker": ticker.strip().upper(),
        "ticker_yf": ticker_yf,
        "es_cripto": es_cripto,
        "precio": precio,
        "timeframe": clave_tf,
        "timeframe_nombre": cfg["nombre"],
        "timeframe_unidad": cfg["unidad"],
        "vela_en_curso": vela_en_curso(df, cfg["unidad"]),
        "rsi": rsi_ctx,
        "medias": medias,
        "fibonacci": fibonacci,
        "divergencias": divergencias,
        "volumen": volumen,
        "atr": atr,
        "macd": calcular_macd(df),
        "obv": calcular_obv(df),
        "estructura": detectar_estructura(df),
        "roc": calcular_roc(df),
        "escenarios": escenarios,
        "cruce": cruce,
        "fase": detectar_fase(df),
        "ath": distancia_maximo_historico(df_diario),
        "rango_52s": rango_52_semanas(df_diario),
        "variacion": calcular_variacion_plazos(df_diario),
        "semaforo": semaforo,
    }


def resumen_timeframe(ticker, timeframe, solo_cerradas=False):
    """
    Lectura corta de un timeframe, para mostrar el contexto de los tres marcos en las
    alertas (ej: "alcista (sobre EMA20/50/200) · HH/HL · RSI 55 · MACD positivo").
    """
    tec = analisis_tecnico_completo(ticker, timeframe, solo_cerradas=solo_cerradas)
    m, precio = tec["medias"], tec["precio"]
    sobre = [n for n in ("20", "50", "200") if precio >= m[f"ema{n}"]]
    if len(sobre) == 3:
        tendencia = "alcista (sobre EMA20/50/200)"
    elif not sobre:
        tendencia = "bajista (bajo EMA20/50/200)"
    else:
        tendencia = f"mixta (sobre EMA{'/'.join(sobre)})"

    partes = [tendencia]
    est = tec["estructura"]["tipo"]
    if est in ("alcista", "bajista"):
        partes.append("HH/HL" if est == "alcista" else "LH/LL")
    partes.append(f"RSI {round(tec['rsi']['valor'])}")
    macd = tec["macd"]
    if macd.get("cruce"):
        partes.append(f"cruce MACD {macd['cruce']}")
    elif macd.get("macd") is not None:
        partes.append(f"MACD {'positivo' if macd['positivo'] else 'negativo'}, {macd['impulso']}")
    return {"timeframe": timeframe, "nombre": tec["timeframe_nombre"], "semaforo": tec["semaforo"],
            "tecnico": tec, "texto": " · ".join(partes)}


def analisis_multitimeframe(ticker, marcos=("diario", "semanal", "4h"), solo_cerradas=False):
    """Resumen de los tres marcos del sistema de alertas (diario manda; semanal y 4h dan contexto)."""
    return {tf: resumen_timeframe(ticker, tf, solo_cerradas) for tf in marcos}
