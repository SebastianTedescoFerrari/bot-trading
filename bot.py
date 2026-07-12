"""
bot.py — Bot de Telegram del proyecto de trading.

Comandos:
  /start           → mensaje de bienvenida y ayuda
  /revisar         → corre TODA la watchlist y manda un reporte por activo
  /revisar GRUPO   → corre solo un grupo (us / arg / cripto)
  /TICKER          → análisis completo de un activo (ej: /baba, /nvda, /btc)
  /TICKER HORIZONTE→ mismo análisis en otro horizonte (ej: /nvda semanal, /nvda 1h)

Cómo funciona:
  - Vos le mandás el comando por Telegram.
  - El bot baja datos actuales, calcula valuación y técnico, y te contesta.
  - No corre solo: responde cuando VOS lo disparás (decisión de diseño).

Setup (esto lo hace Claude Code con vos):
  1. pip install python-telegram-bot yfinance pandas numpy
  2. Crear un bot con @BotFather en Telegram y copiar el token.
  3. Pegar el token en config/config.py (ver config/ejemplo_config.py).
  4. python bot.py
"""

import asyncio
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from modulos.reporte import armar_reporte
from modulos.tecnico import resolver_timeframe
from config.config import TELEGRAM_TOKEN, WATCHLIST, WATCHLIST_GRUPOS

# Pausa entre activos en /revisar, para no golpear los límites de Yahoo/Telegram.
PAUSA_ENTRE_ACTIVOS = 0.6

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    grupos = ", ".join(WATCHLIST_GRUPOS.keys())
    msg = (
        "👋 Bot de trading listo.\n\n"
        "Comandos:\n"
        f"• /revisar — corre TODA tu watchlist ({len(WATCHLIST)} activos)\n"
        f"• /revisar grupo — solo un grupo ({grupos})\n"
        "   ej: /revisar us, /revisar arg, /revisar cripto\n"
        "• /TICKER — análisis de un activo (ej: /baba, /nvda, /btc)\n"
        "• /TICKER horizonte — mismo análisis en otro horizonte:\n"
        "   /nvda semanal, /nvda 1h\n\n"
        "Te muestro valuación y técnico por separado. "
        "Nunca es recomendación: la decisión final es tuya."
    )
    await update.message.reply_text(msg)


async def revisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /revisar [grupo]: sin grupo corre todo; con grupo corre solo ese bloque.
    arg = context.args[0].lower() if context.args else None
    if arg is None:
        tickers, etiqueta = WATCHLIST, "toda la watchlist"
    elif arg in WATCHLIST_GRUPOS:
        tickers, etiqueta = WATCHLIST_GRUPOS[arg], f"grupo {arg.upper()}"
    else:
        grupos = ", ".join(WATCHLIST_GRUPOS.keys())
        await update.message.reply_text(
            f"⚠️ Grupo '{arg}' no existe. Usá: {grupos} "
            f"(o /revisar sin nada para correr todo)."
        )
        return

    await update.message.reply_text(
        f"🔍 Corriendo {etiqueta} ({len(tickers)} activos). "
        f"Esto puede tardar un rato, te voy mandando de a uno..."
    )
    for ticker in tickers:
        try:
            reporte = armar_reporte(ticker)
            await update.message.reply_text(reporte, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error con {ticker}: {e}")
        await asyncio.sleep(PAUSA_ENTRE_ACTIVOS)
    await update.message.reply_text(f"✅ Listo, terminé de revisar {etiqueta}.")


async def analizar_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # El comando es el propio ticker, con un horizonte opcional: /baba semanal -> "baba", "semanal"
    partes = update.message.text.lstrip("/").strip().split()
    if not partes:
        return
    ticker = partes[0].upper()
    horizonte = partes[1] if len(partes) > 1 else None

    try:
        resolver_timeframe(horizonte)
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return

    await update.message.reply_text(f"🔍 Analizando {ticker}...")
    try:
        reporte = armar_reporte(ticker, horizonte)
        await update.message.reply_text(reporte, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ No pude analizar {ticker}: {e}\n"
            f"¿Está bien escrito el ticker? (ej: BABA, NVDA, CVX)"
        )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("revisar", revisar))

    # Cualquier otro /comando se interpreta como un ticker.
    # (python-telegram-bot: capturamos por regex de comando genérico)
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.COMMAND, analizar_ticker))

    # Modo de ejecución:
    #  - En Hugging Face Spaces (existe SPACE_HOST/SPACE_ID) usamos WEBHOOK: Telegram
    #    le pega a la URL pública del Space, lo que además lo mantiene despierto.
    #  - En local (sin esas variables) usamos polling, como siempre.
    # ¿Hay una URL pública (Render / HF)? -> modo WEBHOOK. Si no -> polling (local).
    public_url = os.getenv("RENDER_EXTERNAL_URL")  # Render lo setea automáticamente
    if not public_url:
        space_host = os.getenv("SPACE_HOST")
        if not space_host:
            space_id = os.getenv("SPACE_ID")  # HF: "usuario/nombre-space"
            if space_id:
                space_host = space_id.replace("/", "-").lower() + ".hf.space"
        if space_host:
            public_url = f"https://{space_host}"

    if public_url:
        port = int(os.getenv("PORT", "7860"))
        url_path = TELEGRAM_TOKEN  # ruta secreta del webhook
        webhook_url = f"{public_url.rstrip('/')}/{url_path}"
        logging.info("Bot en modo webhook: %s", webhook_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        logging.info("Bot corriendo (polling). Mandale /start en Telegram.")
        app.run_polling()


if __name__ == "__main__":
    main()
