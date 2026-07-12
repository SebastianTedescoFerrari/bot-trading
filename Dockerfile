# Imagen para correr el bot en JustRunMy.App (build por Docker).
FROM python:3.11-slim

WORKDIR /app

# 1) Dependencias primero (aprovecha la cache de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Código del bot
COPY . .

# El token NO se hornea en la imagen: JustRunMy inyecta las variables de
# entorno TELEGRAM_TOKEN y FMP_API_KEY en tiempo de ejecución (panel).

# Sin buffer, para que los logs salgan en vivo en el panel.
ENV PYTHONUNBUFFERED=1

# El bot escucha Telegram por polling (no expone ningún puerto).
CMD ["python", "bot.py"]
