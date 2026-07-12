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


def evaluar_valuacion(ticker):
    """Semáforo de valuación con explicación en criollo."""
    info = yf.Ticker(ticker).info

    pe_actual = info.get("trailingPE")
    peg = info.get("pegRatio")
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

    # --- Consenso de analistas ---
    target_mean = info.get("targetMeanPrice")
    target_low = info.get("targetLowPrice")
    target_high = info.get("targetHighPrice")
    precio = info.get("currentPrice") or info.get("regularMarketPrice")
    n_analistas = info.get("numberOfAnalystOpinions")

    if target_mean and precio:
        upside = (target_mean - precio) / precio * 100
        resultado["consenso"] = {
            "target": round(target_mean, 2),
            "rango": (round(target_low, 2) if target_low else None,
                      round(target_high, 2) if target_high else None),
            "upside_pct": round(upside, 1),
            "n_analistas": n_analistas,
            "frase": (f"Los analistas ven un precio objetivo promedio de ${round(target_mean,2)} "
                      f"(rango ${round(target_low,2)}–${round(target_high,2)}), "
                      f"un {'+' if upside>=0 else ''}{round(upside,1)}% desde hoy. "
                      f"Basado en {n_analistas} analistas."),
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
