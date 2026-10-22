#!/usr/bin/env python3
"""Timeshift recorder: pulls a throttled HLS panel with parallel Range
requests and republishes a sliding-window playlist (~WINDOW x 5 s delay).

Env:
  SOURCE  media playlist URL or its base directory (default: the Caracol panel)
  OUT     output directory served by nginx (default /data)
  WINDOW  segments kept in the playlist (60 x 5 s = 5 min)
  CONNS   parallel Range connections per segment (24 measured ~1.3x realtime)
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import signal
import sys
import time
import urllib.request

SOURCE = os.environ.get("SOURCE", "http://138.121.15.230:9002/CARACOL/tracks-v1a1/mono.m3u8")
OUT = os.environ.get("OUT", "/data")
CONNS = int(os.environ.get("CONNS", "24"))
WINDOW = int(os.environ.get("WINDOW", "60"))
POLL = float(os.environ.get("POLL", "1.5"))

PLAYLIST = SOURCE if SOURCE.endswith(".m3u8") else SOURCE.rstrip("/") + "/mono.m3u8"
BASE_DIR = PLAYLIST.rsplit("/", 1)[0]
INDEX_FILE = os.path.join(OUT, "segments.json")
PLAYLIST_FILE = os.path.join(OUT, "index.m3u8")

os.makedirs(OUT, exist_ok=True)
stop = False


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def fetch(url, timeout=8, headers=None, method=None):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)


def get_playlist():
    body, _ = fetch(PLAYLIST, 6)
    text = body.decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ".ts" in line:
            out.append(line)
    return out


def fetch_range(url, a, b):
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{b}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if data:
                return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5)
    raise IOError(f"range {a}-{b}: {last}")


def download(url, dest):
    _, hdrs = fetch(url, 8, method="HEAD")
    size = int(hdrs.get("Content-Length", "0"))
    if not size:
        raise IOError("no Content-Length")
    part = (size + CONNS - 1) // CONNS
    chunks = [None] * CONNS
    with cf.ThreadPoolExecutor(max_workers=CONNS) as ex:
        futs = {ex.submit(fetch_range, url, i * part, min(size - 1, (i + 1) * part - 1)): i
                for i in range(CONNS)}
        for f in cf.as_completed(futs):
            chunks[futs[f]] = f.result()
    data = b"".join(chunks)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.rename(tmp, dest)
    return len(data)


def load_index():
    try:
        with open(INDEX_FILE) as fh:
            idx = json.load(fh)
        return [e for e in idx if os.path.isfile(os.path.join(OUT, e["file"]))]
    except Exception:  # noqa: BLE001
        return []


def save_index(idx):
    tmp = INDEX_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(idx, fh)
    os.rename(tmp, INDEX_FILE)


def write_playlist(idx):
    keep = idx[-WINDOW:]
    if not keep:
        return
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:5",
             f"#EXT-X-MEDIA-SEQUENCE:{keep[0]['seq']}"]
    for e in keep:
        lines += ["#EXTINF:5.000,", e["file"]]
    tmp = PLAYLIST_FILE + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.rename(tmp, PLAYLIST_FILE)
    keep_files = {e["file"] for e in keep}
    for f in os.listdir(OUT):
        if re.match(r"^seg_[A-Za-z0-9]+\.ts$", f) and f not in keep_files:
            try:
                os.remove(os.path.join(OUT, f))
            except OSError:
                pass


def handle_sigterm(*_):
    global stop
    stop = True


def main():
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    idx = load_index()
    seq = idx[-1]["seq"] if idx else 0
    seen = {e["path"] for e in idx}
    log(f"start source={PLAYLIST} out={OUT} window={WINDOW} conns={CONNS}")
    log(f"recovered {len(idx)} segments, next seq {seq + 1}")
    pool = cf.ThreadPoolExecutor(max_workers=2)
    pending = {}
    last_status = 0
    while not stop:
        try:
            for path in get_playlist():
                if path in seen:
                    continue
                seen.add(path)
                seq += 1
                url = path if path.startswith("http") else f"{BASE_DIR}/{path}"
                name = "seg_" + hashlib.sha1(path.encode()).hexdigest()[:12] + ".ts"
                dest = os.path.join(OUT, name)
                pending[pool.submit(download, url, dest)] = (seq, path, name)
        except Exception as e:  # noqa: BLE001
            log(f"playlist error: {e}")
        for fut in list(pending):
            if not fut.done():
                continue
            seq_i, path, name = pending.pop(fut)
            try:
                n = fut.result()
                idx.append({"seq": seq_i, "path": path, "file": name})
                save_index(idx)
                write_playlist(idx)
                log(f"seg {seq_i} ok ({n/1024/1024:.1f} MB) total={len(idx)}")
            except Exception as e:  # noqa: BLE001
                log(f"seg {seq_i} FAIL {e}")
        if time.time() - last_status > 60:
            last_status = time.time()
            log(f"status: {len(idx)} segments, window {min(len(idx), WINDOW)}/{WINDOW}")
        time.sleep(POLL)
    pool.shutdown(wait=False)
    log("stopped")


if __name__ == "__main__":
    main()
