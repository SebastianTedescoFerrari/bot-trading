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

_VACIO = {"enviados": {}, "cola": [], "ultimo_resumen": None}


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


def toca_resumen(estado, ahora, hora):
    """¿Ya es la hora del resumen y todavía no se mandó hoy?"""
    return ahora.hour >= hora and estado.get("ultimo_resumen") != ahora.date().isoformat()


def marcar_resumen(estado, ahora):
    estado["ultimo_resumen"] = ahora.date().isoformat()


def limpiar(estado, ahora, dias=30):
    """Borra registros viejos para que el archivo no crezca para siempre."""
    limite = ahora - timedelta(days=dias)
    estado["enviados"] = {k: v for k, v in estado["enviados"].items()
                          if datetime.fromisoformat(v) >= limite}
