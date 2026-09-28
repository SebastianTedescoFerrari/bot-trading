"""
filtro_ia.py — Filtro de relevancia y resumen de noticias con Google Gemini (plan gratis).

Dos pasadas por corrida, para cuidar la cuota gratuita:
  1. Filtro: UNA consulta con todos los titulares nuevos -> cuáles valen la pena,
     urgencia e importancia. Incluye política y geopolítica, no solo economía.
  2. Análisis: solo para las elegidas -> qué está pasando, consecuencias a favor y
     en contra, por qué le importa a Sebastián y qué activos de su watchlist toca.

Nunca se manda una noticia sin pasar por el filtro: si Gemini no responde (cuota agotada,
error), las notas quedan pendientes para la corrida siguiente.
La clave va como parámetro de la URL: nunca se imprime la URL.
"""

import json
import time

import requests

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_REGIONES = ["EE.UU.", "Europa", "España", "Argentina", "China", "Japón", "Asia",
             "Medio Oriente", "América Latina", "Global"]


class IANoDisponible(Exception):
    """Gemini no respondió (cuota, red, clave): las notas quedan para la próxima corrida."""


INSTRUCCIONES_FILTRO = """Sos el editor de noticias de Sebastián, un inversor argentino que vive en España.
Invierte en acciones de EE.UU., ADRs argentinos, índices globales, cripto, oro y petróleo.
Su watchlist: {watchlist}.
Recibís un lote de notas recién publicadas (en varios idiomas). Elegí SOLO las que merece recibir.

Es RELEVANTE si cumple al menos uno:
- Decisión o señal de un banco central (Fed, BCE, Banco de Japón, Banco Popular de China, BCRA, Banco de Inglaterra).
- Dato macro importante (inflación, empleo, PBI, actividad, comercio) o una sorpresa frente a lo esperado.
- Política y geopolítica con peso mundial o regional, AUNQUE el impacto económico sea indirecto: elecciones y
  sus resultados, cambios de gobierno, crisis institucionales, guerras y escaladas militares, acuerdos o rupturas
  diplomáticas, sanciones, aranceles, conflictos comerciales, grandes protestas.
- Política y economía de Argentina con impacto nacional (medidas del gobierno, Congreso, deuda, dólar,
  riesgo país, FMI, reservas).
- Política y economía de España o la Unión Europea con impacto nacional o europeo.
- Noticias que mueven un activo de la watchlist o su sector.
- Cambios regulatorios importantes (cripto, bancos, energía, tecnología e IA).
- Grandes shocks (catástrofes, atentados, crisis financieras) con impacto en mercados o en la estabilidad de un país.

NO es relevante: opinión sin dato nuevo, notas de color o curiosidades, finanzas personales, guías y "cómo hacer",
espectáculos, deportes, cotizaciones de rutina sin novedad (ej: "así abre el dólar hoy"), clickbait, predicciones
de precio sin fundamento, noticias locales sin impacto nacional, empresas chicas fuera de la watchlist.

Además:
- Si varias notas del lote cuentan el MISMO hecho (aunque estén en otro idioma), elegí solo la más completa.
- Si una nota cuenta un hecho que ya está en "YA ENVIADAS", no la elijas (salvo que traiga una novedad importante).
- urgencia "alta" solo si conviene saberlo YA: decisión de tasas, dato macro con gran sorpresa, escalada bélica,
  resultado electoral, anuncio de aranceles o sanciones, derrumbe o disparada fuerte de mercados, default o crisis
  cambiaria. Todo lo demás es "normal".
- importancia de 1 (menor) a 5 (enorme): cuánto cambia el panorama para un inversor.
Sé exigente: mejor pocas noticias buenas que muchas mediocres.
Devolvé solo las elegidas, con su número "i" del lote."""

INSTRUCCIONES_ANALISIS = """Sos el analista de noticias de Sebastián, un inversor argentino que vive en España.
Su watchlist: {watchlist}.
Para cada noticia escribí, en español rioplatense, claro y sin tecnicismos innecesarios:
- titulo: titular corto en español (traducilo si viene en otro idioma).
- region: una de {regiones}.
- tema: 1 a 3 palabras (ej: Política monetaria, Elecciones, Guerra, Aranceles, Inflación, Empresas, Energía, Cripto).
- que_pasa: 3 a 5 líneas que expliquen qué está pasando y el contexto necesario para entenderlo.
- a_favor: 1 a 3 consecuencias POSITIVAS posibles (para la economía, los mercados o activos concretos).
- en_contra: 1 a 3 consecuencias NEGATIVAS o riesgos posibles.
- por_que: 1 o 2 líneas sobre por qué le importa a Sebastián (sus activos, Argentina o España).
- activos: tickers de su watchlist que se verían afectados (solo de la lista; vacía si ninguno).
Reglas: basate SOLO en la información de la nota y en contexto general conocido. NO inventes cifras, fechas,
nombres ni declaraciones que no estén en la nota. Si la nota trae poca información, sé breve y aclaralo.
Las consecuencias son efectos posibles, no certezas: usá "podría", "suele", "presiona"."""

_ESQUEMA_FILTRO = {
    "type": "OBJECT",
    "properties": {"elegidas": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {
            "i": {"type": "INTEGER"},
            "urgencia": {"type": "STRING", "enum": ["alta", "normal"]},
            "importancia": {"type": "INTEGER"},
        },
        "required": ["i", "urgencia", "importancia"],
    }}},
    "required": ["elegidas"],
}

_ESQUEMA_ANALISIS = {
    "type": "OBJECT",
    "properties": {"notas": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {
            "i": {"type": "INTEGER"},
            "titulo": {"type": "STRING"},
            "region": {"type": "STRING", "enum": _REGIONES},
            "tema": {"type": "STRING"},
            "que_pasa": {"type": "STRING"},
            "a_favor": {"type": "ARRAY", "items": {"type": "STRING"}},
            "en_contra": {"type": "ARRAY", "items": {"type": "STRING"}},
            "por_que": {"type": "STRING"},
            "activos": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["i", "titulo", "region", "tema", "que_pasa", "a_favor", "en_contra", "por_que", "activos"],
    }}},
    "required": ["notas"],
}


ultimo_modelo = None   # el modelo que respondió la última consulta (para el registro)


def elegir_modelos(api_key, preferidos):
    """
    Modelos a usar, en orden: los 'preferidos' que existen con esta clave y, de respaldo,
    otros 'flash' vigentes. Ojo: que un modelo figure en la lista no garantiza que ande
    (ej: los 2.5 figuran pero ya no atienden claves nuevas): eso lo resuelve _consultar
    pasando al siguiente.
    """
    try:
        r = requests.get(f"{_BASE}/models", params={"key": api_key, "pageSize": 200}, timeout=20)
    except requests.RequestException as e:
        raise IANoDisponible(f"no pude conectar con Gemini ({type(e).__name__})")
    if r.status_code != 200:
        raise IANoDisponible(f"Gemini rechazó la clave o la consulta ({r.status_code})")
    disponibles = {m["name"].split("/")[-1] for m in r.json().get("models", [])
                   if "generateContent" in m.get("supportedGenerationMethods", [])}
    orden = [m for m in preferidos if m in disponibles]
    respaldo = sorted((m for m in disponibles if "flash" in m and m not in orden and not any(
        x in m for x in ("image", "tts", "audio", "live", "transcribe", "omni", "robotics", "computer",
                         "preview", "2.5", "2.0", "1.5"))), reverse=True)
    if not orden + respaldo:
        raise IANoDisponible("no encontré un modelo Gemini 'flash' disponible con esta clave")
    return orden + respaldo


def _consultar(api_key, modelos, instrucciones, contenido, esquema):
    """
    Una consulta a Gemini con respuesta JSON validada por esquema. Si un modelo está saturado
    (503) o sin cuota (429), lo reintenta una vez y después pasa al siguiente; si no existe
    (404), pasa directo al siguiente. Si fallan todos: IANoDisponible.
    """
    global ultimo_modelo
    cuerpo = {"systemInstruction": {"parts": [{"text": instrucciones}]},
              "contents": [{"role": "user", "parts": [{"text": contenido}]}],
              "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                   "responseSchema": esquema}}
    motivo = "sin modelos"
    for modelo in modelos:
        for intento in range(2):
            try:
                r = requests.post(f"{_BASE}/models/{modelo}:generateContent", params={"key": api_key},
                                  json=cuerpo, timeout=120)
            except requests.RequestException as e:
                motivo = f"sin conexión ({type(e).__name__})"
                time.sleep(3)
                continue
            if r.status_code == 200:
                try:
                    partes = r.json()["candidates"][0]["content"]["parts"]
                    texto = next(p["text"] for p in reversed(partes) if "text" in p and not p.get("thought"))
                    datos = json.loads(texto)
                except (KeyError, IndexError, ValueError, StopIteration):
                    motivo = f"{modelo} devolvió una respuesta inesperada"
                    break
                ultimo_modelo = modelo
                return datos
            if r.status_code in (429, 500, 503, 504):
                motivo = f"{modelo} {'sin cuota' if r.status_code == 429 else 'saturado'}"
                if intento == 0:
                    time.sleep(8)
                continue
            motivo = f"{modelo} error {r.status_code}"
            break   # 404 (ya no existe), 400, etc.: al siguiente modelo
    raise IANoDisponible(f"Gemini no disponible ahora (último intento: {motivo})")


def filtrar(notas, ya_enviadas, watchlist, api_key, modelos):
    """Pasada 1: devuelve [(nota, urgencia, importancia)] de las que valen la pena."""
    if not notas:
        return []
    lote = "\n".join(f"[{i}] ({n['medio']}) {n['titulo']}" + (f" — {n['resumen'][:220]}" if n["resumen"] else "")
                     for i, n in enumerate(notas))
    previas = "\n".join(f"- {t}" for t in ya_enviadas[-40:]) or "(ninguna)"
    datos = _consultar(api_key, modelos, INSTRUCCIONES_FILTRO.format(watchlist=watchlist),
                       f"YA ENVIADAS (últimas 48 h):\n{previas}\n\nLOTE:\n{lote}", _ESQUEMA_FILTRO)
    elegidas, vistos = [], set()
    for e in datos.get("elegidas", []):
        i = e.get("i")
        if isinstance(i, int) and 0 <= i < len(notas) and i not in vistos:
            vistos.add(i)
            elegidas.append((notas[i], e.get("urgencia", "normal"), max(1, min(5, int(e.get("importancia", 3))))))
    return elegidas


def analizar(elegidas, watchlist, tickers_validos, api_key, modelos, por_consulta=6):
    """
    Pasada 2: para cada elegida escribe qué pasa, consecuencias a favor y en contra, etc.
    Devuelve (analizadas, pendientes). Si Gemini se corta a mitad, lo que falte queda pendiente.
    """
    instrucciones = INSTRUCCIONES_ANALISIS.format(watchlist=watchlist, regiones=", ".join(_REGIONES))
    analizadas, pendientes = [], []
    for inicio in range(0, len(elegidas), por_consulta):
        tanda = elegidas[inicio:inicio + por_consulta]
        texto = "\n\n".join(f"[{i}] ({n['medio']}) {n['titulo']}\nResumen de la nota: {n['resumen'] or '(sin resumen)'}"
                            for i, (n, _, _) in enumerate(tanda))
        try:
            datos = _consultar(api_key, modelos, instrucciones, texto, _ESQUEMA_ANALISIS)
        except IANoDisponible:
            pendientes += tanda + elegidas[inicio + por_consulta:]
            break
        por_i = {a.get("i"): a for a in datos.get("notas", [])}
        for i, (nota, urgencia, importancia) in enumerate(tanda):
            a = por_i.get(i)
            if not a:
                pendientes.append((nota, urgencia, importancia))
                continue
            a["activos"] = [t for t in a.get("activos", []) if t.upper() in tickers_validos]
            analizadas.append({**a, "nota": nota, "urgencia": urgencia, "importancia": importancia})
        time.sleep(2)   # respeta el límite de consultas por minuto del plan gratis
    return analizadas, pendientes
