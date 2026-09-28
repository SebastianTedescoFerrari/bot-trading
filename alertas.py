"""
alertas.py — Corrida única del sistema de alertas (técnicas + noticias).

La ejecuta GitHub Actions cada 30 min (07:00–23:00, hora de Madrid). En cada corrida:
  1. TÉCNICO: revisa cada activo de ALERTAS_ACTIVOS (config.py) con las reglas de senales.py.
     Descarta lo ya enviado en las últimas 24 h (anti-spam). Lo urgente sale ya, con el
     detalle completo; lo demás va al resumen compacto de las 08:00.
  2. NOTICIAS: junta las fuentes RSS, Gemini elige las relevantes (economía, política y
     geopolítica) y explica qué pasa y sus consecuencias. Las urgentes salen ya; el resto
     va a la próxima tanda (NOTICIAS_HORAS_TANDA: 08:00 y 20:00). Con NOTICIAS_MODO = "log"
     solo se muestran en el registro.

Uso:
  python alertas.py                      SIMULACIÓN: muestra qué mandaría. No envía ni guarda nada.
  python alertas.py --enviar             Manda a Telegram y guarda data/enviados.json.
Opciones:
  --tickers NVDA,BTC                     Solo esos activos.
  --estado RUTA --guardar-estado         Usa/guarda otro archivo de estado (para probar el anti-spam).
  --forzar-resumen                       Manda el resumen aunque no sean las 08:00.
  --ignorar-horario                      Corre aunque sea fuera de 07:00–23:00 (corridas manuales).
  --sin-noticias / --solo-noticias       Corre solo uno de los dos motores.
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
from modulos import filtro_ia as IA
from modulos.mensajes import (item_resumen, linea_resumen, mensaje_noticia, mensaje_senales, otras_noticias,
                              resumen_compacto)
from modulos.noticias import recolectar
from modulos.senales import detectar_senales
from modulos.tecnico import analisis_multitimeframe

_MAX_NOTICIAS_URGENTES = 5   # por corrida: si hay más, las siguientes van a la próxima tanda

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


def dentro_de_horario(ahora):
    """
    ¿Estamos dentro del horario de alertas (HORARIO_ALERTAS, hora de Madrid)?
    GitHub Actions programa en UTC y no sabe de horario de verano: el cron cubre una franja
    más amplia y acá se descarta lo que cae afuera. Se tolera hasta 23:15 por las demoras
    habituales de los cron de GitHub.
    """
    desde, hasta = C.HORARIO_ALERTAS
    return desde <= ahora.hour < hasta or (ahora.hour == hasta and ahora.minute < 15)


def correr_noticias(est, ahora, despachar, imprimir_encoladas, forzar=False):
    """Motor 2: junta noticias, Gemini las elige y explica, y manda (o encola) las que importan."""
    stats = {"nuevas": 0, "elegidas": 0, "urgentes": 0, "encoladas": 0}
    if not C.GEMINI_API_KEY:
        print("[noticias] falta GEMINI_API_KEY: el motor de noticias no corre")
        return stats
    # El plan gratis de Gemini da 20 consultas por día y por modelo: una pasada por hora como máximo.
    ultima = est.get("ultima_corrida_noticias")
    if ultima and not forzar:
        minutos = (ahora - datetime.fromisoformat(ultima)).total_seconds() / 60
        if minutos < C.NOTICIAS_CADA_MIN - 10:
            print(f"[noticias] última pasada hace {minutos:.0f} min: la próxima en la corrida siguiente "
                  f"(cada {C.NOTICIAS_CADA_MIN} min, para cuidar la cuota gratis de Gemini)")
            return stats
    notas, descartar = recolectar(C.NOTICIAS_FUENTES, est["noticias_vistas"], C.NOTICIAS_HORAS)
    E.marcar_vistas(est, descartar, ahora)
    stats["nuevas"] = len(notas)
    if not notas:
        return stats

    watchlist = ", ".join(f"{a['ticker']} ({a['nombre']})" for a in C.ALERTAS_ACTIVOS)
    tickers = {a["ticker"].upper() for a in C.ALERTAS_ACTIVOS}
    try:
        modelos = IA.elegir_modelos(C.GEMINI_API_KEY, C.GEMINI_MODELOS)
        analizadas = IA.seleccionar_y_analizar(notas, [x["titulo"] for x in est["noticias_enviadas"]],
                                               watchlist, tickers, C.GEMINI_API_KEY, modelos)
    except IA.IANoDisponible as e:
        print(f"[noticias] {e}. Quedan para la próxima corrida (nunca se mandan sin filtrar).")
        return stats
    E.marcar_vistas(est, [n["id"] for n in notas], ahora)   # todo el lote ya pasó por la IA
    est["ultima_corrida_noticias"] = ahora.isoformat()
    stats["elegidas"] = len(analizadas)
    print(f"[noticias] {len(notas)} nuevas · {len(analizadas)} elegidas y explicadas por {IA.ultimo_modelo}")

    for a in sorted(analizadas, key=lambda x: -x["importancia"]):
        nota, texto = a["nota"], mensaje_noticia(a, C.ZONA_HORARIA)
        if a["urgencia"] == "alta" and stats["urgentes"] < _MAX_NOTICIAS_URGENTES:
            if not despachar(texto, "NOTICIA URGENTE — sale en esta corrida"):
                continue   # no se marca: se reintenta en la próxima corrida
            stats["urgentes"] += 1
        else:
            if imprimir_encoladas:
                print(f"\n----- [noticia — va a la próxima tanda de noticias] -----\n{texto}")
            est["cola_noticias"].append({"id": nota["id"], "titulo": a["titulo"], "medio": nota["medio"],
                                         "link": nota["link"], "importancia": a["importancia"], "mensaje": texto})
            stats["encoladas"] += 1
        E.marcar_vistas(est, [nota["id"]], ahora)
        E.registrar_noticia(est, a["titulo"], ahora)
    return stats


def tanda_noticias(est, ahora, despachar, forzar):
    """En cada horario de NOTICIAS_HORAS_TANDA: las más importantes completas y el resto con links."""
    turno = E.turno_pendiente(est, ahora, C.NOTICIAS_HORAS_TANDA, "ultimo_resumen_noticias")
    if forzar and not turno:
        turno = f"{ahora.date().isoformat()}@{ahora.hour}"
    if not turno:
        return
    cola = sorted(est["cola_noticias"], key=lambda x: -x["importancia"])
    if not cola:
        est["ultimo_resumen_noticias"] = turno
        return
    completas, resto = cola[:C.NOTICIAS_MAX_RESUMEN], cola[C.NOTICIAS_MAX_RESUMEN:]
    etiqueta = f"NOTICIAS {int(turno.split('@')[1]):02d}:00"
    ok = despachar(f"🗞️ Noticias destacadas · {len(completas)} de {len(cola)} (de mayor a menor importancia)",
                   f"{etiqueta} — cabecera")
    ok = ok and all(despachar(x["mensaje"], etiqueta) for x in completas)
    if ok and resto:
        ok = all(despachar(p, f"{etiqueta} — otras", es_html=True) for p in otras_noticias(resto))
    if ok:
        est["cola_noticias"] = []
        est["ultimo_resumen_noticias"] = turno


def main():
    ap = argparse.ArgumentParser(description="Corrida del sistema de alertas técnicas")
    ap.add_argument("--enviar", action="store_true", help="mandar a Telegram (sin esto: simulación)")
    ap.add_argument("--tickers", help="lista separada por comas (ej: NVDA,BTC)")
    ap.add_argument("--estado", help="ruta del archivo de estado (default: data/enviados.json)")
    ap.add_argument("--guardar-estado", action="store_true", help="guardar el estado aunque sea simulación")
    ap.add_argument("--forzar-resumen", action="store_true", help="mandar el resumen aunque no sea la hora")
    ap.add_argument("--ignorar-horario", action="store_true", help="correr aunque sea fuera de HORARIO_ALERTAS")
    ap.add_argument("--sin-noticias", action="store_true", help="solo alertas técnicas")
    ap.add_argument("--solo-noticias", action="store_true", help="solo noticias")
    args = ap.parse_args()

    if args.enviar and not C.TELEGRAM_CHAT_ID:
        sys.exit("Falta TELEGRAM_CHAT_ID (variable de entorno o config/secreto.py).")

    inicio = time.time()
    ahora = datetime.now(ZoneInfo(C.ZONA_HORARIA))
    if not args.ignorar_horario and not dentro_de_horario(ahora):
        print(f"Fuera de horario ({ahora:%H:%M} en Madrid; se corre de {C.HORARIO_ALERTAS[0]:02d}:00 "
              f"a {C.HORARIO_ALERTAS[1]:02d}:00). No hago nada.")
        return
    ruta = args.estado or RUTA_ESTADO
    guardar = args.enviar or args.guardar_estado
    est = E.cargar(ruta)

    activos = [] if args.solo_noticias else C.ALERTAS_ACTIVOS
    if args.tickers:
        pedidos = {x.strip().upper() for x in args.tickers.split(",")}
        activos = [a for a in activos if a["ticker"].upper() in pedidos]

    enviando_noticias = args.enviar and C.NOTICIAS_MODO == "enviar"
    modo = "ENVÍO REAL" if args.enviar else "SIMULACIÓN (no se envía nada)"
    print(f"== Alertas · {ahora:%Y-%m-%d %H:%M} {C.ZONA_HORARIA} · {len(activos)} activos · {modo} · "
          f"noticias: {'no' if args.sin_noticias else ('se envían' if enviando_noticias else 'solo registro')} ==")

    def despachar(texto, etiqueta, es_html=False):
        if args.enviar:
            return enviar_telegram(texto, es_html)
        print(f"\n----- [{etiqueta}] -----\n{texto}")
        return True

    def despachar_noticia(texto, etiqueta, es_html=False):
        if enviando_noticias:
            return enviar_telegram(texto, es_html)
        nota_log = " · modo log, no se envía" if args.enviar else ""
        print(f"\n----- [{etiqueta}{nota_log}] -----\n{texto}")
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

    # ── Noticias ──
    nov = {"nuevas": 0, "elegidas": 0, "urgentes": 0, "encoladas": 0}
    if not args.sin_noticias:
        try:
            nov = correr_noticias(est, ahora, despachar_noticia, imprimir_encoladas=not enviando_noticias,
                                  forzar=args.ignorar_horario or args.solo_noticias)
            tanda_noticias(est, ahora, despachar_noticia, args.forzar_resumen)
        except Exception as e:   # un problema con las noticias no frena lo técnico
            errores.append(f"noticias: {type(e).__name__}: {e}")

    E.limpiar(est, ahora)
    if guardar:
        E.guardar(ruta, est)

    print(f"\n== Fin · {time.time() - inicio:.0f}s · técnico: {urgentes} urgentes, {encolados} al resumen · "
          f"noticias: {nov['nuevas']} nuevas, {nov['elegidas']} elegidas, {nov['urgentes']} urgentes, "
          f"{nov['encoladas']} a la tanda · errores: {len(errores)} ==")
    for err in errores:
        print("  ERROR", err)


if __name__ == "__main__":
    main()
