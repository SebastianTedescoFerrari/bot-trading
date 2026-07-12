---
title: Bot Trading
emoji: 📈
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Bot de Trading — Proyecto de Sebastián

Bot de Telegram que analiza tu watchlist con datos de mercado actuales.
Le mandás un comando y te devuelve **valuación** y **técnico** por separado,
en criollo, sin mezclar los dos semáforos.

---

## Qué hace

- `/revisar` — corre toda la watchlist y te manda un reporte por activo.
- `/baba`, `/nvda`, `/cvx`, etc. — análisis de un activo puntual.
- Corre **solo cuando vos lo disparás** (no bombardea con alertas).

Para cada activo te muestra:

**Valuación** (¿está barata o cara?)
- P/E actual vs su histórico, con escalones de intensidad (15%, 20%, 30%...).
- PEG (ajuste por crecimiento) como refuerzo.
- Comparación con pares del sector.
- Consenso de analistas (target, rango, cuántos en compra/venta).
- Proyección técnica **especulativa** (marcada como tal, nunca predicción).
- Todo explicado en criollo, con el número técnico entre paréntesis.

**Técnico** (¿es buen momento en el gráfico?)
- RSI con contexto de zona (avisa cuando se acerca a los extremos).
- Medias móviles (EMA20/50/200) y posición del precio.
- Fibonacci trazado sobre el máximo/mínimo de 6 meses.
- Divergencias **candidatas** (para confirmar a ojo).

---

## Cómo ponerlo a andar (con Claude Code)

Abrí esta carpeta en Claude Code y pedile que te guíe con estos pasos.
Cada uno es simple; Claude Code los ejecuta con vos.

### 1. Instalar dependencias
```
pip install -r requirements.txt
```

### 2. Crear el bot en Telegram
- En Telegram, buscá **@BotFather**.
- Mandale `/newbot`, seguí los pasos, y te va a dar un **token** (una cadena larga).
- Copialo.

### 3. Configurar
- Copiá `config/ejemplo_config.py` a `config/config.py`.
- Pegá tu token en `TELEGRAM_TOKEN`.
- (Opcional) Ajustá la `WATCHLIST`.

### 4. Correr
```
python bot.py
```
- Abrí tu bot en Telegram, mandale `/start`.
- Probá `/baba` y deberías recibir el análisis.

---

## Estructura del proyecto

```
bot-trading/
├── bot.py                    # Archivo principal (comandos de Telegram)
├── requirements.txt          # Dependencias
├── README.md                 # Este archivo
├── modulos/
│   ├── tecnico.py            # RSI, medias, Fibonacci, divergencias
│   ├── valuacion.py          # P/E, PEG, pares, consenso, proyección
│   └── reporte.py            # Arma el mensaje de Telegram
└── config/
    ├── ejemplo_config.py     # Plantilla (copiá a config.py)
    └── config.py             # TU config con el token (NO subir a GitHub)
```

---

## Mejoras para la fase 2 (cuando esté andando)

- **P/E histórico real:** conectar Financial Modeling Prep (API free) para la
  comparación de valuación fina. Hoy el gancho está en `valuacion.py`, falta
  enchufar la fuente. Pediselo a Claude Code cuando quieras.
- **BTC / cripto:** yfinance soporta `BTC-USD`. El análisis técnico funciona
  igual; la valuación (P/E, PEG) no aplica a cripto, así que para BTC conviene
  una variante que solo corra la parte técnica + on-chain. A definir.
- **Comparación de pares automática:** hoy es referencial; se puede automatizar
  pasando una lista de competidores por sector.
- **Alertas proactivas (opcional):** si algún día querés que avise solo cuando
  algo entra en zona, se puede agregar un scheduler. Por ahora, a propósito,
  corre solo cuando vos lo disparás.

---

## Notas importantes

- El bot da **análisis, no recomendaciones**. La decisión final es tuya.
- Las **divergencias** son candidatas: confirmalas mirando el gráfico.
- La **proyección** es especulativa por diseño: muestra escenarios, no predice.
- Nunca subas `config/config.py` con tu token a un repo público.
