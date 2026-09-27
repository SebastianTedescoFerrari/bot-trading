"""
alertas.py — Corrida única del sistema de alertas técnicas.

La ejecuta GitHub Actions cada 30 min (07:00–23:00, hora de Madrid). En cada corrida:
  1. Revisa cada activo de ALERTAS_ACTIVOS (config.py) con las reglas de senales.py.
  2. Descarta lo ya enviado en las últimas 24 h (anti-spam, data/enviados.json).
  3. Lo urgente sale ya, con el detalle completo; lo demás queda en cola.
  4. Si ya son las 08:00 y el resumen de hoy no salió, lo manda: un solo mensaje compacto
     con una línea por activo (el detalle de cualquiera se pide al bot con /TICKER).

Uso:
  python alertas.py                      SIMULACIÓN: muestra qué mandaría. No envía ni guarda nada.
  python alertas.py --enviar             Manda a Telegram y guarda data/enviados.json.
Opciones:
  --tickers NVDA,BTC                     Solo esos activos.
  --estado RUTA --guardar-estado         Usa/guarda otro archivo de estado (para probar el anti-spam).
  --forzar-resumen                       Manda el resumen aunque no sean las 08:00.
"""

import argparse
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import config as C
from modulos import estado as E
from modulos.mensajes import item_resumen, linea_resumen, mensaje_senales, resumen_compacto
from modulos.senales import detectar_senales
from modulos.tecnico import analisis_multitimeframe

RUTA_ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "enviados.json")


def enviar_telegram(texto, es_html=False):
    """Manda un mensaje al chat configurado. Devuelve True si Telegram lo aceptó."""
    datos = {"chat_id": C.TELEGRAM_CHAT_ID, "text": texto, "disable_web_page_preview": True}
    if es_html:
        datos["parse_mode"] = "HTML"
    try:
        r = requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_TOKEN}/sendMessage",
                          json=datos, timeout=20)
    except requests.RequestException as e:
        print(f"[telegram] error de red: {type(e).__name__}")
        return False
    if not r.ok:
        # Nunca imprimir la URL: lleva el token.
        print(f"[telegram] rechazado ({r.status_code}): {r.json().get('description', '')}")
    time.sleep(0.5)   # Telegram limita la cantidad de mensajes por segundo
    return r.ok


def main():
    ap = argparse.ArgumentParser(description="Corrida del sistema de alertas técnicas")
    ap.add_argument("--enviar", action="store_true", help="mandar a Telegram (sin esto: simulación)")
    ap.add_argument("--tickers", help="lista separada por comas (ej: NVDA,BTC)")
    ap.add_argument("--estado", help="ruta del archivo de estado (default: data/enviados.json)")
    ap.add_argument("--guardar-estado", action="store_true", help="guardar el estado aunque sea simulación")
    ap.add_argument("--forzar-resumen", action="store_true", help="mandar el resumen aunque no sea la hora")
    args = ap.parse_args()

    if args.enviar and not C.TELEGRAM_CHAT_ID:
        sys.exit("Falta TELEGRAM_CHAT_ID (variable de entorno o config/secreto.py).")

    inicio = time.time()
    ahora = datetime.now(ZoneInfo(C.ZONA_HORARIA))
    ruta = args.estado or RUTA_ESTADO
    guardar = args.enviar or args.guardar_estado
    est = E.cargar(ruta)

    activos = C.ALERTAS_ACTIVOS
    if args.tickers:
        pedidos = {x.strip().upper() for x in args.tickers.split(",")}
        activos = [a for a in activos if a["ticker"].upper() in pedidos]

    modo = "ENVÍO REAL" if args.enviar else "SIMULACIÓN (no se envía nada)"
    print(f"== Alertas · {ahora:%Y-%m-%d %H:%M} {C.ZONA_HORARIA} · {len(activos)} activos · {modo} ==")

    def despachar(texto, etiqueta, es_html=False):
        if args.enviar:
            return enviar_telegram(texto, es_html)
        print(f"\n----- [{etiqueta}] -----\n{texto}")
        return True

    urgentes = encolados = 0
    errores = []
    for activo in activos:
        try:
            senales, info = detectar_senales(activo, C.UMBRAL_MOVIMIENTO, C.VOLUMEN_MINIMO_CONVICCION,
                                             C.MOVIMIENTO_INTRADIA, C.FIB_NIVELES_ALERTA)
            nuevas = [s for s in senales if not E.ya_enviada(est, s["clave"], ahora, C.ANTISPAM_HORAS)]
            if not nuevas:
                continue
            claves = [s["clave"] for s in nuevas]
            if any(s["urgente"] for s in nuevas):
                # Urgente: detalle completo con el contexto de los tres marcos
                mtf = analisis_multitimeframe(activo["yf"], solo_cerradas=True)
                if despachar(mensaje_senales(activo, nuevas, mtf, info["precio_actual"]),
                             "URGENTE — sale en esta corrida"):
                    urgentes += 1
                    for c in claves:
                        E.marcar_enviada(est, c, ahora)
            else:
                # No urgente: una línea en el resumen compacto de las 08:00
                item = item_resumen(activo, nuevas)
                if not args.enviar:
                    print(f"\n----- [va al resumen de las {C.HORA_RESUMEN:02d}:00] -----\n{linea_resumen(item)}")
                E.encolar(est, item, ahora)
                encolados += 1
                for c in claves:
                    E.marcar_enviada(est, c, ahora)   # el anti-spam cuenta desde que se detecta
        except Exception as e:   # un activo con problemas no frena al resto
            errores.append(f"{activo['ticker']}: {type(e).__name__}: {e}")

    # ── Resumen diario (un solo mensaje compacto; se parte solo si es muy largo) ──
    if E.toca_resumen(est, ahora, C.HORA_RESUMEN) or args.forzar_resumen:
        cola = est["cola"]
        if cola:
            partes = resumen_compacto(cola, ahora)
            if all(despachar(p, "RESUMEN DE LAS 08:00", es_html=True) for p in partes):
                est["cola"] = []
                E.marcar_resumen(est, ahora)
        else:
            E.marcar_resumen(est, ahora)   # nada que mandar hoy

    E.limpiar(est, ahora)
    if guardar:
        E.guardar(ruta, est)

    print(f"\n== Fin · {time.time() - inicio:.0f}s · urgentes: {urgentes} · al resumen: {encolados} · "
          f"en cola: {len(est['cola'])} · errores: {len(errores)} ==")
    for err in errores:
        print("  ERROR", err)


if __name__ == "__main__":
    main()
