"""
noticias.py — Recolección de noticias (sección 6 del diseño, MOTOR 2).

Baja las fuentes RSS de config.NOTICIAS_FUENTES (todas gratuitas), limpia el texto,
se queda con lo nuevo (publicado en las últimas NOTICIAS_HORAS y no visto antes) y
junta la misma noticia cuando aparece en varios medios. El filtro de relevancia y el
resumen los hace después filtro_ia.py: acá no se descarta nada por tema.
"""

import calendar
import hashlib
import html
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import feedparser
import requests

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
_MAX_POR_CORRIDA = 150   # tope de notas nuevas por corrida (cuida la cuota de la IA)


def _limpiar(texto, largo=300):
    """Saca HTML, entidades y espacios de más."""
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto or ""))
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:largo] + ("…" if len(texto) > largo else "")


def _normalizar(titulo):
    """Título sin tildes, signos ni mayúsculas, para comparar duplicados."""
    t = unicodedata.normalize("NFKD", titulo.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s+", " ", t)).strip()


def _bajar_fuente(fuente):
    """Devuelve las notas de una fuente (lista vacía si falla: una fuente caída no frena nada)."""
    try:
        r = requests.get(fuente["url"], headers=_UA, timeout=20)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except Exception as e:
        print(f"[noticias] {fuente['medio']}: no respondió ({type(e).__name__})")
        return []

    notas = []
    for e in feed.entries:
        titulo, link = _limpiar(e.get("title"), 250), e.get("link")
        if not titulo or not link:
            continue
        medio = fuente["medio"]
        fuente_gn = e.get("source", {}).get("title") if "news.google.com" in fuente["url"] else None
        if fuente_gn:   # Google News agrega " - Medio" al título
            titulo = re.sub(rf"\s+-\s+{re.escape(fuente_gn)}$", "", titulo)
            medio = fuente_gn
        fecha = e.get("published_parsed") or e.get("updated_parsed")
        resumen = _limpiar(e.get("summary") or e.get("description"), 300)
        if _normalizar(resumen).startswith(_normalizar(titulo)[:60]):
            resumen = ""   # Google News repite el título como resumen: no aporta nada
        notas.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:16],
            "titulo": titulo,
            "resumen": resumen,
            "link": link,
            "medio": medio,
            "publicada": (datetime.fromtimestamp(calendar.timegm(fecha), tz=timezone.utc).isoformat()
                          if fecha else None),
        })
    return notas


def _deduplicar(notas, umbral=0.82):
    """
    Junta la misma noticia publicada por varios medios; se queda con la de resumen más
    completo. Devuelve (elegidas, ids de las repetidas descartadas).
    """
    elegidas, repetidas = [], []
    for n in sorted(notas, key=lambda x: len(x["resumen"]), reverse=True):
        clave = _normalizar(n["titulo"])
        if any(SequenceMatcher(None, clave, _normalizar(e["titulo"])).ratio() >= umbral for e in elegidas):
            repetidas.append(n["id"])
        else:
            elegidas.append(n)
    return elegidas, repetidas


def recolectar(fuentes, vistas, horas=6, ahora=None):
    """
    Baja todas las fuentes y devuelve (notas nuevas, ids a marcar como vistas sin procesar:
    las viejas y las repetidas).

    - Nueva = no está en 'vistas' y se publicó en las últimas 'horas'.
    - Sin fecha (algunos medios no la ponen): cuenta como nueva si nunca se vio; en la
      primera corrida (vistas vacío) se ignora, para no arrancar con todo el archivo del medio.
    """
    ahora = ahora or datetime.now(timezone.utc)
    limite = ahora - timedelta(hours=horas)
    primera_vez = not vistas

    with ThreadPoolExecutor(max_workers=8) as ex:
        todas = [n for lote in ex.map(_bajar_fuente, fuentes) for n in lote]

    nuevas, viejas, ids = [], [], set()
    for n in todas:
        if n["id"] in vistas or n["id"] in ids:
            continue
        ids.add(n["id"])
        if n["publicada"]:
            es_nueva = datetime.fromisoformat(n["publicada"]) >= limite
        else:
            es_nueva = not primera_vez
        (nuevas if es_nueva else viejas).append(n)

    nuevas, repetidas = _deduplicar(nuevas)
    nuevas.sort(key=lambda x: x["publicada"] or ahora.isoformat(), reverse=True)
    return nuevas[:_MAX_POR_CORRIDA], [n["id"] for n in viejas] + repetidas
