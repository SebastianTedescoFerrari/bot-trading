# Despliegue en JustRunMy.App — Bot 24/7 gratis, sin tarjeta

Objetivo: que el bot corra en la nube, prendido 24/7, sin depender de tu PC y
sin poner tarjeta. Le mandás el comando por Telegram y responde aunque tu PC esté
apagada.

Host elegido: **JustRunMy.App** — sin tarjeta, panel web autoservicio, always-on
real. Única contra: 256 MB de RAM (justo para pandas; si molesta, optimizamos).

## Cómo se maneja el token (importante)

El token ya NO está escrito en el código. `config/config.py` lo lee así:
1. De la variable de entorno **`TELEGRAM_TOKEN`** → se usa en la nube.
2. Si no está, de **`config/secreto.py`** → para correr local (ese archivo está
   en `.gitignore`, no se sube). Lo mismo con `FMP_API_KEY`.

---

# Plan A — Subir un ZIP (lo más simple)

El archivo listo: **`bot-trading-DEPLOY.zip`** (en la carpeta del proyecto).
Incluye `config/secreto.py`, así que **funciona sin tener que setear variables**.

1. 🧑 Entrá a https://justrunmy.app/ y registrate con tu email (sin tarjeta).
2. 🧑 **Create application → Simple**. Si dice "Servers are busy", apretá
   **"Check again"** cada 1–2 min hasta que se libere.
3. 🧑 Subí **`bot-trading-DEPLOY.zip`**.
4. 🧑 Comando de arranque: `python bot.py` · (si lo pide) instalar:
   `pip install -r requirements.txt` · Python: `3.11`.
5. Start → pestaña **Logs** → tenés que ver `Bot corriendo. Mandale /start...`.

---

# Plan B — Git Push (Claude Code lo maneja desde la PC)

Ya está TODO preparado: el repo tiene el commit inicial, `config.py` sin secretos,
`Procfile` (`worker: python bot.py`) y `runtime.txt` (python-3.11).

1. 🧑 En JustRunMy: **Create application → Advanced → Git Push**.
2. 🧑 Copiá la **URL del remoto** (y credenciales/instrucciones) que te muestre,
   y pegásela a Claude Code.
3. 🤖 Claude Code agrega el remoto y hace el `push` por vos:
   `git remote add justrunmy <URL>` y `git push justrunmy master`.
4. 🧑 En el panel, cargá las **variables de entorno**:
   - `TELEGRAM_TOKEN` = (tu token de @BotFather)
   - `FMP_API_KEY` = (tu API key de Financial Modeling Prep)
   > Como el token no viaja en el repo, en Git Push hay que cargarlo acá.
5. 🧑 Start command (si no toma el Procfile): `python bot.py`.
6. Start → **Logs** → `Bot corriendo...`.

---

## Paso final (cualquiera de los dos) — Probar

En Telegram: `/start`, después `/baba`. Luego **apagá tu PC** y probá `/nvda`:
tiene que seguir contestando. ✅

## Comandos que pueden aparecer en los logs

- **Error de memoria (OOM / killed):** 256 MB quedó corto → avisar, se optimiza.
- **"no pude analizar":** puede ser bloqueo de Yahoo a la IP del datacenter →
  se resuelve con reintentos, proxy, o cambiando la fuente de precios.

## Si el token se compromete

@BotFather → `/revoke` para regenerarlo. Actualizá `config/secreto.py` (local) y
la variable de entorno en el panel. Nunca reuses ese token para otra cosa.

---

## Nota

`deploy/bot-trading.service` y `deploy/setup_servidor.sh` son de un plan
alternativo (VPS propio con systemd). No se usan en JustRunMy.App.
