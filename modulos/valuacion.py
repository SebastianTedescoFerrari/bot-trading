"""
valuacion.py — Análisis de valuación del bot.

Para un ticker calcula:
  - Si está barata/cara según P/E actual vs su histórico, con escalones de intensidad
  - PEG como refuerzo (ajuste por crecimiento)
  - Comparación contra pares del sector
  - Consenso de analistas (target promedio, rango, cuántos en compra/venta)
  - Proyección técnica especulativa (marcada como tal)

TODO se explica en criollo; el número técnico va como respaldo entre paréntesis.

Fuentes: yfinance para casi todo. Para fundamentales más finos se puede
sumar Financial Modeling Prep (API key gratis) — ver config/ejemplo_config.py.
"""

import time

import yfinance as yf
import requests

try:
    from config.config import FMP_API_KEY
except Exception:  # por si config.py todavía no existe
    FMP_API_KEY = ""


# Escalones de intensidad definidos con Sebastián: 15%, 20%, y de ahí de a 10.
ESCALONES = [15, 20, 30, 40, 50, 60, 70, 80, 90]

# Caché en memoria del P/E histórico por ticker, para no pegarle a FMP en cada consulta
# (útil sobre todo en /revisar, que corre muchos activos seguidos).
_CACHE_PE_HISTORICO = {}

# Caché del .info de yfinance (el pedido más pesado y el que más se rate-limitea).
_CACHE_INFO = {}


def _info_yf(ticker, ttl=21600):
    """
    Trae el .info de yfinance con caché (6h; los fundamentales casi no cambian intradía)
    y reintentos. Si Yahoo lo frena (rate limit), devuelve {} en vez de romper: así la
    valuación degrada pero el resto del reporte (lo técnico) igual sale. Solo se usa como
    fallback: para acciones de EE.UU. la valuación viene de FMP (más confiable).
    """
    hit = _CACHE_INFO.get(ticker)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    for i in range(3):
        try:
            info = yf.Ticker(ticker).info
            if info:
                _CACHE_INFO[ticker] = (time.time(), info)
                return info
        except Exception:
            pass
        if i < 2:
            time.sleep(1.0 * (i + 1))
    return {}


def pe_historico_fmp(ticker, anios=5):
    """
    Baja de Financial Modeling Prep el P/E promedio de los últimos 'anios' años,
    que usamos como "P/E normal/histórico" del activo.

    Devuelve (valor, motivo):
      - (float, "ok")             si lo pudo calcular
      - (None,  "sin_key")        si no hay API key cargada
      - (None,  "sin_datos")      si FMP no tiene histórico para ese ticker
      - (None,  "error")          si falló la llamada (red, límite, etc.)
    Sin key, el bot sigue funcionando igual (solo queda esta lectura apagada).
    """
    if not FMP_API_KEY:
        return None, "sin_key"
    if ticker in _CACHE_PE_HISTORICO:
        return _CACHE_PE_HISTORICO[ticker]

    try:
        # Endpoint "stable" (los v3 quedaron discontinuados por FMP en ago-2025).
        # Campo priceToEarningsRatio = P/E de cada año fiscal.
        url = (f"https://financialmodelingprep.com/stable/ratios"
               f"?symbol={ticker}&period=annual&limit={anios}&apikey={FMP_API_KEY}")
        r = requests.get(url, timeout=10)
        if r.status_code == 402:
            # El plan gratis de FMP no cubre este símbolo (típico en ADRs argentinos).
            resultado = (None, "no_cubierto")
        elif r.status_code != 200:
            resultado = (None, "error")
        else:
            data = r.json()
            if not isinstance(data, list):
                resultado = (None, "error")
            else:
                # Descartamos años con P/E negativo (empresa en pérdida): distorsionan el promedio.
                pes = [d.get("priceToEarningsRatio") for d in data if isinstance(d, dict)]
                pes = [p for p in pes if p and p > 0]
                resultado = (round(sum(pes) / len(pes), 1), "ok") if pes else (None, "sin_datos")
    except Exception:
        resultado = (None, "error")

    _CACHE_PE_HISTORICO[ticker] = resultado
    return resultado


# Caché de la valuación FMP (P/E actual, PEG, target de analistas).
_CACHE_FMP_VAL = {}
_FMP_BASE = "https://financialmodelingprep.com/stable"


def datos_fmp_valuacion(ticker, ttl=21600):
    """
    Trae de FMP (endpoint stable) el P/E actual (TTM), el PEG y el target de analistas.
    Es más confiable desde la nube que el .info de Yahoo (que se rate-limitea seguido).
    Cachea 6h. Devuelve {} si el activo no está en el plan free (ADRs -> 402) o si falla.
    """
    if not FMP_API_KEY:
        return {}
    hit = _CACHE_FMP_VAL.get(ticker)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]

    res = {}
    try:
        r = requests.get(f"{_FMP_BASE}/ratios-ttm?symbol={ticker}&apikey={FMP_API_KEY}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and d:
                pe = d[0].get("priceToEarningsRatioTTM")
                peg = d[0].get("priceToEarningsGrowthRatioTTM")
                if pe and pe > 0:
                    res["pe_actual"] = round(pe, 1)
                if peg and peg > 0:
                    res["peg"] = round(peg, 2)
        r2 = requests.get(f"{_FMP_BASE}/price-target-summary?symbol={ticker}&apikey={FMP_API_KEY}", timeout=10)
        if r2.status_code == 200:
            d2 = r2.json()
            if isinstance(d2, list) and d2:
                tgt = d2[0].get("lastYearAvgPriceTarget")
                cnt = d2[0].get("lastYearCount")
                if tgt:
                    res["target"] = round(float(tgt), 2)
                if cnt:
                    res["n_analistas"] = cnt
    except Exception:
        pass

    _CACHE_FMP_VAL[ticker] = (time.time(), res)
    return res


def _intensidad(desvio_pct):
    """
    Dado el % de desvío del P/E vs su histórico, devuelve el escalón alcanzado.
    Ej: -33% -> alcanzó el escalón 30. +22% -> escalón 20.
    """
    magnitud = abs(desvio_pct)
    alcanzado = 0
    for e in ESCALONES:
        if magnitud >= e:
            alcanzado = e
    return alcanzado


def evaluar_valuacion(ticker, precio_actual=None):
    """
    Semáforo de valuación con explicación en criollo.
    Para acciones de EE.UU. los datos vienen de FMP (confiable desde la nube);
    Yahoo .info queda como fallback (ADRs, o si FMP no cubre algo).
    precio_actual: precio ya calculado en la parte técnica (para el upside vs target).
    """
    fmp = datos_fmp_valuacion(ticker)
    # Si FMP ya trae lo esencial (caso acciones US), evitamos depender del .info de Yahoo.
    info = {} if (fmp.get("pe_actual") and fmp.get("target")) else _info_yf(ticker)

    pe_actual = fmp.get("pe_actual") or info.get("trailingPE")
    peg = fmp.get("peg") or info.get("pegRatio")
    sector = info.get("sector", "su sector")

    # --- P/E vs histórico (vía FMP) ---
    # yfinance no da el P/E histórico; lo completamos con Financial Modeling Prep.
    # Sin API key, pe_historico queda None y se muestra el aviso correspondiente.
    pe_historico, motivo_pe = pe_historico_fmp(ticker)

    resultado = {
        "ticker": ticker,
        "pe_actual": round(pe_actual, 1) if pe_actual else None,
        "peg": round(peg, 2) if peg else None,
        "sector": sector,
    }

    # --- Semáforo principal por P/E vs histórico ---
    if pe_actual and pe_historico:
        desvio = (pe_actual - pe_historico) / pe_historico * 100
        escalon = _intensidad(desvio)
        if desvio <= -15:
            color = "verde"
            frase = (f"🟢 Barata (~{escalon}% bajo lo normal). Hoy pagás menos por cada peso "
                     f"de ganancia de la empresa que lo que se pagó en promedio los últimos años. "
                     f"(P/E {round(pe_actual,1)} vs {round(pe_historico,1)} histórico)")
        elif desvio >= 15:
            color = "rojo"
            frase = (f"🔴 Cara (~{escalon}% sobre lo normal). Estás pagando más por cada peso de "
                     f"ganancia que lo habitual; el mercado espera bastante de ella. "
                     f"(P/E {round(pe_actual,1)} vs {round(pe_historico,1)} histórico)")
        else:
            color = "amarillo"
            frase = (f"🟡 En su precio normal. El P/E está cerca de su promedio histórico, "
                     f"ni barata ni cara. (P/E {round(pe_actual,1)} vs {round(pe_historico,1)})")
        resultado["desvio_pct"] = round(desvio, 1)
        resultado["escalon"] = escalon
    else:
        color = "amarillo"
        if motivo_pe == "sin_key":
            frase = ("🟡 Comparación con su P/E histórico apagada. "
                     "Cargá tu API key gratis de FMP en config.py para prenderla.")
        elif motivo_pe == "no_cubierto":
            frase = ("🟡 El P/E histórico de este activo no está en el plan gratis de FMP "
                     "(típico en ADRs argentinos). El resto de la valuación sigue abajo.")
        elif motivo_pe == "sin_datos":
            frase = ("🟡 FMP no tiene P/E histórico de este activo "
                     "(común en empresas nuevas o sin ganancias).")
        elif motivo_pe == "error":
            frase = ("🟡 No pude consultar el P/E histórico ahora "
                     "(problema de red o límite de FMP). Probá de nuevo en un rato.")
        else:  # había histórico pero falta el P/E actual (empresa en pérdida, etc.)
            frase = ("🟡 Sin P/E actual para comparar "
                     "(puede estar en pérdidas o sin ganancias reportadas).")
        if pe_actual:
            frase += f" P/E actual: {round(pe_actual,1)}."

    resultado["color"] = color
    resultado["frase_principal"] = frase

    # --- PEG como refuerzo, en criollo ---
    if peg:
        if peg < 1:
            resultado["frase_peg"] = (f"Y considerando lo rápido que crece, sigue barata. "
                                      f"(PEG {round(peg,2)} — abajo de 1 es buena señal)")
        elif peg <= 2:
            resultado["frase_peg"] = (f"Ajustada por su crecimiento, está en un precio razonable. "
                                      f"(PEG {round(peg,2)})")
        else:
            resultado["frase_peg"] = (f"Incluso considerando su crecimiento, se paga caro. "
                                      f"(PEG {round(peg,2)} — arriba de 2 es señal de caro)")
    else:
        resultado["frase_peg"] = None

    # --- Consenso de analistas (target de FMP o, si no, de Yahoo) ---
    target_mean = fmp.get("target") or info.get("targetMeanPrice")
    target_low = info.get("targetLowPrice")    # el rango solo lo da Yahoo; FMP da el promedio
    target_high = info.get("targetHighPrice")
    n_analistas = fmp.get("n_analistas") or info.get("numberOfAnalystOpinions")
    precio = precio_actual or info.get("currentPrice") or info.get("regularMarketPrice")

    if target_mean and precio:
        upside = (target_mean - precio) / precio * 100
        if target_low and target_high:
            frase = (f"Los analistas ven un precio objetivo promedio de ${round(target_mean,2)} "
                     f"(rango ${round(target_low,2)}–${round(target_high,2)}), "
                     f"un {'+' if upside>=0 else ''}{round(upside,1)}% desde hoy. "
                     f"Basado en {n_analistas} analistas.")
        else:
            frase = (f"Los analistas ven un precio objetivo promedio de ${round(target_mean,2)}, "
                     f"un {'+' if upside>=0 else ''}{round(upside,1)}% desde hoy. "
                     f"Basado en {n_analistas} analistas.")
        resultado["consenso"] = {
            "target": round(target_mean, 2),
            "rango": (round(target_low, 2) if target_low else None,
                      round(target_high, 2) if target_high else None),
            "upside_pct": round(upside, 1),
            "n_analistas": n_analistas,
            "frase": frase,
        }
    else:
        resultado["consenso"] = None

    return resultado


def proyeccion_especulativa(tecnico):
    """
    Proyección técnica SIEMPRE marcada como especulativa, con escenario alcista Y bajista.
    Se basa en los niveles de Fibonacci (resistencia arriba, soporte abajo). No es predicción.
    """
    fib = tecnico["fibonacci"]
    return {
        "alcista": f"si rompe {fib['resistencia_nombre']} (${fib['resistencia']}) al alza, "
                   f"el siguiente objetivo técnico es la zona superior del rango (${fib['maximo']}).",
        "bajista": f"si pierde {fib['soporte_nombre']} (${fib['soporte']}), "
                   f"puede buscar la zona inferior del rango (${fib['minimo']}).",
        "aviso": "⚠ ESPECULATIVO — escenario técnico sobre niveles conocidos, NO es una predicción.",
    }
