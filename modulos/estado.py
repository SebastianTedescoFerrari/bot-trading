"""
estado.py — Memoria del sistema de alertas (data/enviados.json).

Guarda:
  - "enviados": qué señal se mandó y cuándo (anti-spam: la misma señal del mismo
    activo no se repite antes de ANTISPAM_HORAS).
  - "cola": señales no urgentes que esperan el resumen diario de las 08:00.
  - "ultimo_resumen": fecha del último resumen enviado (para mandarlo una vez por día).

En la nube, GitHub Actions guarda este archivo en el repo después de cada corrida.
"""

import copy
import json
import os
from datetime import datetime, timedelta

_VACIO = {
    # Alertas técnicas
    "enviados": {}, "cola": [], "ultimo_resumen": None,
    # Noticias: vistas (ya pasaron por el filtro), enviadas (títulos recientes, para no
    # repetir un hecho contado por otro medio), cola para la tanda de las 08:00.
    "noticias_vistas": {}, "noticias_enviadas": [], "cola_noticias": [], "ultimo_resumen_noticias": None,
}


def cargar(ruta):
    """Lee el estado. Si no existe o está roto, arranca vacío (nunca frena una corrida)."""
    if not os.path.exists(ruta):
        return copy.deepcopy(_VACIO)
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        print(f"[estado] {ruta} ilegible: arranco con estado vacío")
        return copy.deepcopy(_VACIO)
    for clave, valor in _VACIO.items():
        datos.setdefault(clave, copy.deepcopy(valor))
    return datos


def guardar(ruta, estado):
    """Escribe el estado de forma atómica (archivo temporal + reemplazo)."""
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, ruta)


def ya_enviada(estado, clave, ahora, horas=24):
    """¿Esta señal ya salió (o quedó en cola) hace menos de 'horas'?"""
    ts = estado["enviados"].get(clave)
    if not ts:
        return False
    return ahora - datetime.fromisoformat(ts) < timedelta(hours=horas)


def marcar_enviada(estado, clave, ahora):
    estado["enviados"][clave] = ahora.isoformat()


def encolar(estado, item, ahora):
    """
    Deja un activo esperando el resumen diario (sin duplicar el mismo grupo de señales).
    'item' trae lo necesario para su línea del resumen; su "id" identifica el grupo.
    """
    if any(x["id"] == item["id"] for x in estado["cola"]):
        return
    estado["cola"].append({**item, "detectada": ahora.isoformat()})


def toca_resumen(estado, ahora, hora, clave="ultimo_resumen"):
    """¿Ya es la hora del resumen y todavía no se mandó hoy? (clave: técnico o noticias)"""
    return ahora.hour >= hora and estado.get(clave) != ahora.date().isoformat()


def marcar_resumen(estado, ahora, clave="ultimo_resumen"):
    estado[clave] = ahora.date().isoformat()


def marcar_vistas(estado, ids, ahora):
    """Noticias que ya pasaron por el filtro (no se vuelven a evaluar)."""
    for i in ids:
        estado["noticias_vistas"][i] = ahora.isoformat()


def registrar_noticia(estado, titulo, ahora):
    """Título de una noticia elegida, para que la IA no repita el mismo hecho contado por otro medio."""
    estado["noticias_enviadas"].append({"titulo": titulo, "ts": ahora.isoformat()})


def limpiar(estado, ahora, dias=30):
    """Borra registros viejos para que el archivo no crezca para siempre."""
    limite = ahora - timedelta(days=dias)
    estado["enviados"] = {k: v for k, v in estado["enviados"].items()
                          if datetime.fromisoformat(v) >= limite}
    semana = ahora - timedelta(days=7)
    estado["noticias_vistas"] = {k: v for k, v in estado["noticias_vistas"].items()
                                 if datetime.fromisoformat(v) >= semana}
    dos_dias = ahora - timedelta(days=2)
    estado["noticias_enviadas"] = [x for x in estado["noticias_enviadas"]
                                   if datetime.fromisoformat(x["ts"]) >= dos_dias]
