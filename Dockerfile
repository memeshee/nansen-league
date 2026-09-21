FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g nansen-cli

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py jev.py league.py nansen_client.py dashboard.py start.sh seed_batch.py ./
COPY static/ ./static/
RUN chmod +x start.sh seed_batch.py

ENV DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8765 \
    TELEGRAM_BOT_USERNAME=righttofight_bot

CMD ["./start.sh"]
