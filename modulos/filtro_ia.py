"""
filtro_ia.py — Filtro de relevancia y explicación de noticias con Google Gemini (plan gratis).

UNA sola consulta por pasada: Gemini recibe todos los titulares nuevos, elige los que
valen la pena (economía, política y geopolítica) y para cada uno explica qué está
pasando, las consecuencias a favor y en contra, por qué le importa a Sebastián y qué
activos de su watchlist toca.

Por qué una sola consulta: el plan gratis permite 20 consultas POR DÍA y por modelo
(cuota GenerateRequestsPerDayPerProjectPerModel-FreeTier, verificada 2026-09-28).

Nunca se manda una noticia sin pasar por el filtro: si Gemini no responde (saturado,
sin cuota, error), las notas quedan para la corrida siguiente.
La clave va como parámetro de la URL: nunca se imprime la URL.
"""

import json
import time

import requests

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_REGIONES = ["EE.UU.", "Europa", "España", "Argentina", "China", "Japón", "Asia",
             "Medio Oriente", "América Latina", "Global"]


class IANoDisponible(Exception):
    """Gemini no respondió (saturado, sin cuota, red, clave): las notas quedan para la próxima corrida."""


INSTRUCCIONES = """Sos el editor y analista de noticias de Sebastián, un inversor argentino que vive en España.
Invierte en acciones de EE.UU., ADRs argentinos, índices globales, cripto, oro y petróleo.
Su watchlist: {watchlist}.
Recibís un lote de notas recién publicadas (en varios idiomas). Elegí SOLO las que merece recibir
(como máximo {maximo}) y explicá cada una.

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

Reglas de selección:
- Si varias notas del lote cuentan el MISMO hecho (aunque estén en otro idioma), elegí solo la más completa.
- Si una nota cuenta un hecho que ya está en "YA ENVIADAS", no la elijas (salvo que traiga una novedad importante).
- urgencia "alta" solo para un hecho que está pasando AHORA y puede mover los mercados HOY: decisión de tasas,
  dato macro con gran sorpresa, escalada bélica, resultado electoral, anuncio de aranceles o sanciones, derrumbe o
  disparada fuerte de mercados, default o crisis cambiaria. Proyecciones, informes, análisis, vencimientos o
  eventos futuros y planes anunciados son "normal" aunque sean importantes. Ante la duda, "normal".
- importancia de 1 (menor) a 5 (enorme): cuánto cambia el panorama para un inversor.
- Sé exigente: mejor pocas noticias buenas que muchas mediocres. Si no hay nada relevante, devolvé la lista vacía.

Cómo escribir: en español rioplatense, claro y sin tecnicismos innecesarios, HABLÁNDOLE DIRECTO A ÉL, de vos
(ej: "tus tecnológicas", "si seguís YPF"), nunca en tercera persona ("Sebastián tiene..."). Su watchlist son
activos que SIGUE, no necesariamente que tiene: no afirmes que tiene posiciones ni inventes otras (bonos, etc.).

Para cada elegida escribí:
- i: su número en el lote.
- titulo: titular corto en español (traducilo si viene en otro idioma).
- region: una de {regiones}.
- tema: 1 a 3 palabras (ej: Política monetaria, Elecciones, Guerra, Aranceles, Inflación, Empresas, Energía, Cripto).
- que_pasa: 3 a 5 líneas que expliquen qué está pasando y el contexto necesario para entenderlo.
- a_favor: 1 a 3 consecuencias POSITIVAS posibles (para la economía, los mercados o activos concretos).
- en_contra: 1 a 3 consecuencias NEGATIVAS o riesgos posibles.
- por_que: 1 o 2 líneas, hablándole a él, sobre por qué le importa (los activos que sigue, Argentina o España).
- activos: tickers de su watchlist afectados DE FORMA DIRECTA (solo de la lista; vacía si ninguno; no agregues
  los que aparecen solo de pasada en la nota).
Basate SOLO en la información de la nota y en contexto general conocido. NO inventes cifras, fechas, nombres ni
declaraciones que no estén en la nota. Si la nota trae poca información, sé breve y aclaralo. Las consecuencias
son efectos posibles, no certezas: usá "podría", "suele", "presiona"."""

_ESQUEMA = {
    "type": "OBJECT",
    "properties": {"elegidas": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {
            "i": {"type": "INTEGER"},
            "urgencia": {"type": "STRING", "enum": ["alta", "normal"]},
            "importancia": {"type": "INTEGER"},
            "titulo": {"type": "STRING"},
            "region": {"type": "STRING", "enum": _REGIONES},
            "tema": {"type": "STRING"},
            "que_pasa": {"type": "STRING"},
            "a_favor": {"type": "ARRAY", "items": {"type": "STRING"}},
            "en_contra": {"type": "ARRAY", "items": {"type": "STRING"}},
            "por_que": {"type": "STRING"},
            "activos": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["i", "urgencia", "importancia", "titulo", "region", "tema", "que_pasa",
                     "a_favor", "en_contra", "por_que", "activos"],
    }}},
    "required": ["elegidas"],
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
    (503), lo reintenta una vez y después pasa al siguiente; sin cuota (429) o inexistente
    (404), pasa directo al siguiente. Si fallan todos: IANoDisponible con el detalle.
    """
    global ultimo_modelo
    cuerpo = {"systemInstruction": {"parts": [{"text": instrucciones}]},
              "contents": [{"role": "user", "parts": [{"text": contenido}]}],
              "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                   "responseSchema": esquema}}
    motivos = []
    for modelo in modelos:
        for intento in range(2):
            try:
                r = requests.post(f"{_BASE}/models/{modelo}:generateContent", params={"key": api_key},
                                  json=cuerpo, timeout=180)
            except requests.RequestException as e:
                motivos.append(f"{modelo} sin conexión ({type(e).__name__})")
                time.sleep(3)
                continue
            if r.status_code == 200:
                try:
                    partes = r.json()["candidates"][0]["content"]["parts"]
                    texto = next(p["text"] for p in reversed(partes) if "text" in p and not p.get("thought"))
                    datos = json.loads(texto)
                except (KeyError, IndexError, ValueError, StopIteration):
                    motivos.append(f"{modelo} respuesta inesperada")
                    break
                ultimo_modelo = modelo
                return datos
            if r.status_code in (500, 503, 504) and intento == 0:
                time.sleep(8)   # saturado: un reintento y al siguiente modelo
                continue
            motivos.append(f"{modelo} {'sin cuota del día' if r.status_code == 429 else ('saturado' if r.status_code in (500, 503, 504) else f'error {r.status_code}')}")
            break
    raise IANoDisponible("Gemini no disponible ahora: " + "; ".join(motivos))


def seleccionar_y_analizar(notas, ya_enviadas, watchlist, tickers_validos, api_key, modelos, maximo=8):
    """
    UNA consulta: elige las notas relevantes y las explica. Devuelve la lista de noticias
    analizadas (cada una con su nota original, urgencia e importancia).
    """
    if not notas:
        return []
    lote = "\n".join(f"[{i}] ({n['medio']}) {n['titulo']}" + (f" — {n['resumen'][:220]}" if n["resumen"] else "")
                     for i, n in enumerate(notas))
    previas = "\n".join(f"- {t}" for t in ya_enviadas[-40:]) or "(ninguna)"
    instrucciones = INSTRUCCIONES.format(watchlist=watchlist, maximo=maximo, regiones=", ".join(_REGIONES))
    datos = _consultar(api_key, modelos, instrucciones,
                       f"YA ENVIADAS (últimas 48 h):\n{previas}\n\nLOTE:\n{lote}", _ESQUEMA)

    resultado, vistos = [], set()
    for a in datos.get("elegidas", []):
        i = a.get("i")
        if not isinstance(i, int) or not 0 <= i < len(notas) or i in vistos:
            continue
        vistos.add(i)
        a["activos"] = [t for t in a.get("activos", []) if str(t).upper() in tickers_validos]
        a["importancia"] = max(1, min(5, int(a.get("importancia", 3))))
        a["urgencia"] = a.get("urgencia", "normal")
        resultado.append({**a, "nota": notas[i]})
    return resultado[:maximo]
