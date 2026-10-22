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

`cosmos-compose.json` es un servapp único (stack `cosmos-stack`) con un volumen
compartido; el HLS sale por el proxy con el hostname por defecto
(`{ServiceName}.{RootHostname}` → `timeshift.<tu-host-de-cosmos>`):

1. ServApps → *Import Docker Compose* (o pegá el JSON) y elegí el nombre.
2. En el paso del hostname, dejá el default o cambialo.
3. Instalá; el dominio se agrega solo en Cosmos → Domains.

Queda en `https://timeshift.<tu-host-de-cosmos>/index.m3u8`. Si es una
Constellation, agregá `"Tunnel": "_ANY_"` al route.

URL para VLC / mpv / Jellyfin (tuner M3U):

```
https://caracoltv.home.mumbach.dev/index.m3u8
```

En el mismo host: `http://localhost:8099/index.m3u8`

### Jellyfin (Live TV)

Jellyfin no acepta el playlist HLS directo como tuner: necesita una lista de
canales. `channels.m3u` la provee (servida por el contenedor `hls`).

1. Dashboard → Live TV → Tuner Devices → `+` → tipo **M3U Tuner**.
2. File or URL: `https://caracoltv.home.mumbach.dev/channels.m3u`.
3. Simultaneous stream limit `0`, guardar.
4. Scheduled Tasks → **Refresh Guide** (o esperar ~1 min).
5. Live TV → Channels → *Caracol TV*.

Guía de programación opcional: TV Guide Data Providers → XMLTV y mapear por
`tvg-id="caracoltv"`.

## Cómo funciona

- `recorder` (Python, sin dependencias) lee el playlist del panel, detecta
  segmentos nuevos y los descarga con `CONNS` conexiones HTTP Range en
  paralelo (el panel limita por conexión).
- Escribe `data/index.m3u8` con los últimos `WINDOW` segmentos, dejando
  siempre `DELAY` segmentos sin publicar entre lo descargado y el borde del
  playlist. Así cada entrada del playlist es definitiva: el archivo ya está
  escrito, renombrado y no se poda mientras siga publicado.
- Los segmentos se conservan `SPARE` (60 s) más allá de cuando salen del
  playlist, así un reproductor que todavía tiene el playlist anterior no pide
  un archivo ya borrado.
- `hls` (nginx) sirve solo `index.m3u8` y `seg_*.ts`, sin listado.
- El atraso lo da el tamaño de la ventana más el delay: `(DELAY + WINDOW) x 5 s`
  de historia disponible, con el borde vivo `DELAY x 5 s` detrás de la
  descarga.
  - `WINDOW=60`, `DELAY=24` → 2 min de atraso y 7 min de historia
  - `WINDOW=120`, `DELAY=24` → 2 min de atraso y 12 min de historia

  Sin `DELAY` (0) el borde del playlist es el último segmento descargado y un
  reproductor puede pedir un archivo que todavía no existe o que se acaba de
  podar; en la práctica eso corta el stream unos segundos cada varios minutos.

## Ajustes

| Variable | Default | Qué hace |
|---|---|---|
| `SOURCE` | panel Caracol | playlist HLS de origen |
| `WINDOW` | 60 | segmentos publicados en el playlist (x5 s) |
| `DELAY` | 24 | segmentos de colchón entre la descarga y el borde del playlist (x5 s) |
| `SPARE` | 12 | segmentos extra en disco después de salir del playlist (x5 s) |
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
