# Timeshift Caracol — Docker

Recibe un HLS con throttling por conexión, lo baja con rangos paralelos y
publica una ventana deslizante de ~5 minutos para ver “en vivo” con atraso.

## Arranque

```bash
docker compose up -d --build
```

Imagen publicada por CI (amd64 + arm64):

```
ghcr.io/fermuch/caracol-tv-timeshifter:latest   # recorder
ghcr.io/fermuch/caracol-tv-timeshifter:hls      # nginx HLS (config incluida)
```

### Cosmos Cloud

`cosmos-compose.json` levanta los dos contenedores con un volumen compartido y
expone el HLS por el proxy de Cosmos:

1. Editá `Host` (`timeshift.example.com`) por tu dominio.
2. Agregá el dominio en Cosmos → Domains (si no está).
3. ServApps → *Import Docker Compose* / pegá el JSON de `cosmos-compose.json`.

Queda en `https://timeshift.<tu-dominio>/index.m3u8`. Si es una Constellation,
agregá `"Tunnel": "_ANY_"` al route.

URL para VLC / mpv / Jellyfin (tuner M3U):

```
http://<IP-DEL-HOST>:8099/index.m3u8
```

En el mismo host: `http://localhost:8099/index.m3u8`

## Cómo funciona

- `recorder` (Python, sin dependencias) lee el playlist del panel, detecta
  segmentos nuevos y los descarga con `CONNS` conexiones HTTP Range en
  paralelo (el panel limita por conexión).
- Escribe `data/index.m3u8` con los últimos `WINDOW` segmentos.
- `hls` (nginx) sirve solo `index.m3u8` y `seg_*.ts`, sin listado.
- El atraso lo da el tamaño de la ventana: `WINDOW x 5 s`.
  - 60 → 5 min
  - 120 → 10 min
  - 360 → 30 min

## Ajustes

| Variable | Default | Qué hace |
|---|---|---|
| `SOURCE` | panel Caracol | playlist HLS de origen |
| `WINDOW` | 60 | segmentos en la ventana (x5 s) |
| `CONNS` | 24 | conexiones Range por segmento |
| `POLL` | 1.5 | segundos entre consultas al playlist |

Cambiá los valores en `docker-compose.yml` y `docker compose up -d`.

## Requisitos y límites

- Ancho de banda del origen: ~400 KB/s para tiempo real. Con 24 conexiones se
  midió ~550 KB/s (1,3x). Si el panel va más lento, subí `CONNS`; si el origen
  es rápido, bajalo.
- Disco: ~1,4 GB/hora de video; con ventana de 5 min, ~120 MB en uso.
- El panel de origen borra segmentos en segundos: el recorder consulta cada
  1,5 s y descarga en el acto. No lo cambies por un `ffmpeg` simple.
- Es un restream no oficial: si cambian la URL o el token, hay que actualizar
  `SOURCE`.
- Si el contenedor se reinicia, retoma el índice (`data/segments.json`) sin
  volver a bajar lo que ya tiene.

## Verificación rápida

```bash
curl -sI http://localhost:8099/index.m3u8
ffprobe -v error -show_entries stream=codec_name,width,height \
  -of default=nw=1 http://localhost:8099/index.m3u8
```
