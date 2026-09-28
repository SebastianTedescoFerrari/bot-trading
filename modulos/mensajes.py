"""
mensajes.py — Formato de las alertas técnicas (sección 5.5 del diseño).

Urgentes: un mensaje por activo con el detalle completo (señal principal, las demás del
mismo activo, contexto de los tres marcos, volumen/ATR, niveles, escenarios y link a
TradingView). Texto plano, para que Telegram no rompa nada con los símbolos de precios.

Resumen de las 08:00: un solo mensaje compacto (HTML), una línea por activo con el
ticker como link al gráfico. El detalle se pide al bot con /TICKER.
"""

import html
from datetime import datetime
from zoneinfo import ZoneInfo

EMOJI_DIRECCION = {"alcista": "🟢", "bajista": "🔴", "neutral": "🟡"}
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def num(x, decimales=2):
    """Número en formato argentino/español: 84.670,93."""
    if x is None:
        return "s/d"
    s = f"{x:,.{decimales}f}"
    return s.replace(",", "·").replace(".", ",").replace("·", ".")


def precio(x, tipo):
    """Precio con la unidad que corresponde al tipo de activo."""
    if x is None:
        return "s/d"
    decimales = 4 if abs(x) < 2 else 2
    if tipo == "tasa":
        return f"{num(x, 3)}%"   # las tasas se leen con 3 decimales (5,184%)
    if tipo in ("indice", "fx", "volatilidad"):
        return num(x, decimales)
    return f"${num(x, decimales)}"


def link_tradingview(simbolo_tv):
    return f"https://www.tradingview.com/chart/?symbol={simbolo_tv}"


def _escenarios(fib, tipo):
    niveles = sorted(set(list(fib["niveles"].values()) + list(fib["extensiones"].values())))
    res, sop = fib["resistencia"], fib["soporte"]
    arriba = next((v for v in niveles if v > res * 1.001), None)
    abajo = next((v for v in reversed(niveles) if v < sop * 0.999), None)
    sube = (f"▲ si cierra el día sobre {precio(res, tipo)} con volumen → habilita subida hacia "
            f"{precio(arriba, tipo)}" if arriba else
            f"▲ si cierra el día sobre {precio(res, tipo)} con volumen → entra en zona de máximos")
    baja = (f"▼ si pierde {precio(sop, tipo)} → busca {precio(abajo, tipo)}" if abajo else
            f"▼ si pierde {precio(sop, tipo)} → queda sin soportes cercanos")
    return [sube, baja]


def mensaje_senales(activo, senales, mtf, precio_actual):
    """Arma el mensaje de un activo con una o varias señales nuevas."""
    tipo = activo["tipo"]
    tec = mtf["diario"]["tecnico"]
    principal = senales[0]
    urgente = any(s["urgente"] for s in senales)

    L = [f"{'🚨 URGENTE · ' if urgente else ''}📊 {activo['ticker']} — {activo['nombre']} · "
         f"{precio(precio_actual, tipo)} · {EMOJI_DIRECCION[principal['direccion']]} SEÑAL: {principal['titulo']}",
         f"Por qué te llega: {principal['por_que']}"]
    if len(senales) > 1:
        L.append("También:")
        L += [f"  {EMOJI_DIRECCION[s['direccion']]} {s['titulo']}" for s in senales[1:]]
    if any(s["baja_conviccion"] for s in senales):
        L.append(f"⚠️ Baja convicción: el volumen de esa vela fue {num(tec['volumen']['ratio'], 1)}x su "
                 f"promedio (menos de 0,7x). Puede ser un amague.")
    L.append("")

    etiquetas = {"diario": "Diario ", "semanal": "Semanal", "4h": "4h     "}
    for tf in ("diario", "semanal", "4h"):
        if tf in mtf:
            L.append(f"{etiquetas[tf]} · {mtf[tf]['texto']}")
    L.append("")

    vol, atr = tec["volumen"], tec["atr"]
    vol_txt = (f"{num(vol['ratio'], 1)}x promedio ({vol['estado']})" if vol.get("ratio") is not None
               else "sin dato de volumen")
    atr_txt = (f"{num(atr['atr'], 3)} pts" if tipo == "tasa"      # en tasas el ATR va en puntos
               else f"{precio(atr['atr'], tipo)} ({num(atr['pct'], 1)}%)")
    L.append(f"Volumen: {vol_txt} · ATR: {atr_txt}")
    fib, r52 = tec["fibonacci"], tec["rango_52s"]
    niveles = f"Niveles: resistencia {precio(fib['resistencia'], tipo)} · soporte {precio(fib['soporte'], tipo)}"
    if r52:
        niveles += f" · máx 52s {precio(r52['maximo'], tipo)} · mín 52s {precio(r52['minimo'], tipo)}"
    L.append(niveles)
    L.append("")

    L.append("Escenarios:")
    L += _escenarios(fib, tipo)
    L.append("")
    L.append(f"📈 Ver en TradingView: {link_tradingview(activo['tv'])}")
    L.append("No es recomendación. Confirmá en el gráfico.")
    return "\n".join(L)


# ═════════════════════════════════════════════════════════════
# NOTICIAS
# ═════════════════════════════════════════════════════════════
BANDERA = {"EE.UU.": "🇺🇸", "Europa": "🇪🇺", "España": "🇪🇸", "Argentina": "🇦🇷", "China": "🇨🇳",
           "Japón": "🇯🇵", "Asia": "🌏", "Medio Oriente": "🌍", "América Latina": "🌎", "Global": "🌍"}


def _hora_local(iso_utc, zona):
    if not iso_utc:
        return None
    return datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(zona)).strftime("%d/%m %H:%M")


def mensaje_noticia(a, zona):
    """
    Una noticia analizada por la IA: qué está pasando, consecuencias a favor y en contra,
    por qué te importa, activos afectados, link y fuente. Texto plano.
    """
    nota = a["nota"]
    etiqueta = "🔴 URGENTE · " if a["urgencia"] == "alta" else "📰 "
    L = [f"{etiqueta}{BANDERA.get(a['region'], '🌍')} {a['region']} · {a['tema']}",
         a["titulo"], "",
         f"Qué está pasando: {a['que_pasa']}", "",
         "Consecuencias:"]
    L += [f"✅ {x}" for x in a["a_favor"][:3]]
    L += [f"⚠️ {x}" for x in a["en_contra"][:3]]
    L += ["", f"Por qué te la mando: {a['por_que']}"]
    if a["activos"]:
        L.append("Afecta: " + " · ".join(a["activos"]))
    L.append(f"🔗 {nota['link']}")
    hora = _hora_local(nota.get("publicada"), zona)
    L.append(f"Fuente: {nota['medio']}" + (f" · {hora}" if hora else ""))
    return "\n".join(L)


def otras_noticias(items, limite=3800):
    """Las noticias que no entran en la tanda completa: una línea con link cada una (HTML)."""
    cabecera = "📰 <b>Otras noticias relevantes</b> (menos importantes; tocá el título para leerla)\n"
    mensajes, actual = [], cabecera
    for x in items:
        linea = (f"• <a href=\"{html.escape(x['link'], quote=True)}\">{html.escape(x['titulo'])}</a> "
                 f"({html.escape(x['medio'])})")
        if len(actual) + len(linea) + 1 > limite:
            mensajes.append(actual)
            actual = ""
        actual += "\n" + linea
    mensajes.append(actual)
    return mensajes


def item_resumen(activo, senales):
    """Lo que se guarda en la cola del resumen para un activo (lo justo para su línea)."""
    return {
        "id": "+".join(sorted(s["clave"] for s in senales)),
        "ticker": activo["ticker"], "nombre": activo["nombre"], "tv": activo["tv"],
        "direccion": senales[0]["direccion"], "titulos": [s["titulo"] for s in senales],
        "baja_conviccion": any(s["baja_conviccion"] for s in senales),
    }


def linea_resumen(item):
    """Una línea del resumen en HTML de Telegram: el ticker es un link a TradingView."""
    titulos = item["titulos"][:3]
    extra = f" (+{len(item['titulos']) - 3})" if len(item["titulos"]) > 3 else ""
    link = html.escape(link_tradingview(item["tv"]), quote=True)
    return (f"{EMOJI_DIRECCION[item['direccion']]} <a href=\"{link}\">{html.escape(item['ticker'])}</a> "
            f"{html.escape(item['nombre'])} · {html.escape(' · '.join(titulos))}{extra}"
            f"{' ⚠️ baja convicción' if item['baja_conviccion'] else ''}")


def resumen_compacto(items, ahora, limite=3800):
    """
    El resumen diario en uno (o, si hay muchos activos, varios) mensajes HTML: una línea por
    activo. El detalle completo de cualquiera se pide al bot con /TICKER.
    """
    dia = f"{_DIAS[ahora.weekday()]} {ahora.strftime('%d/%m')}"
    cabecera = (f"☀️ <b>Resumen técnico · {dia} · {len(items)} activo{'s' if len(items) != 1 else ''}</b>\n"
                f"<i>Señales no urgentes, con velas diarias cerradas. Tocá el ticker para abrir el gráfico.</i>\n")
    pie = ("\nDetalle completo de cualquiera: mandame /TICKER al bot (ej: /MSFT).\n"
           "No es recomendación. Confirmá en el gráfico.")
    mensajes, actual = [], cabecera
    for linea in (linea_resumen(i) for i in items):
        if len(actual) + len(linea) + len(pie) + 2 > limite:
            mensajes.append(actual)
            actual = "<i>(sigue el resumen)</i>\n"
        actual += "\n" + linea
    mensajes.append(actual + "\n" + pie)
    return mensajes
