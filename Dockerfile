FROM python:3.12-alpine

WORKDIR /app
COPY recorder.py /app/recorder.py

ENV OUT=/data \
    WINDOW=60 \
    DELAY=24 \
    SPARE=12 \
    MIN_DELAY=6 \
    CONNS=24 \
    PYTHONUNBUFFERED=1

CMD ["python3", "-u", "/app/recorder.py"]
