FROM python:3.12-slim

WORKDIR /app

COPY world_cup/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El código se monta como volumen en desarrollo (docker-compose)
# En producción se puede copiar con: COPY world_cup/ .

CMD ["python", "web.py"]
