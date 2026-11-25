"""Gira su GitHub Actions: pubblica i reel in coda il cui orario e' arrivato.
Coda: queue/<id>.json  {profile, asset, caption, publish_at_utc, status}
Video: asset della release 'queue' (scaricati con gh, cancellati dopo la pubblicazione).
Token nei Secrets (<PROFILE>_ACCESS_TOKEN, <PROFILE>_IG_USER_ID), mai stampati.
"""
import datetime, glob, json, os, subprocess, time, urllib.error, urllib.parse, urllib.request
import qcrypt

API = "https://graph.facebook.com/v24.0"
MAX_LATE_H = 6
# nome profilo -> alias dei Secrets (P1, P2...), dal Secret PROFILE_ALIAS: {"nome": "p1", ...}
ALIAS = json.loads((os.environ.get("PROFILE_ALIAS") or "{}").strip().lstrip("﻿"))  # ignora il BOM aggiunto da PowerShell


def req(method, url, params=None, data=None, headers=None, timeout=120):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = data if isinstance(data, (bytes, type(None))) else urllib.parse.urlencode(data).encode()
    r = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:500]}")


def publish(profile, video, caption, dry=False):
    al = ALIAS.get(profile, profile).upper()
    tok = os.environ.get(f"{al}_ACCESS_TOKEN")
    ig = os.environ.get(f"{al}_IG_USER_ID")
    if not tok or not ig:
        raise RuntimeError("Secrets mancanti")
    r = req("POST", f"{API}/{ig}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption, "access_token": tok})
    cid, uri = r["id"], r["uri"]
    size = os.path.getsize(video)
    with open(video, "rb") as f:
        up = req("POST", uri, data=f.read(), timeout=1800, headers={
            "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    if not up.get("success", True):
        raise RuntimeError(f"Upload fallito: {up}")
    deadline = time.time() + 15 * 60
    while True:
        s = req("GET", f"{API}/{cid}", {"fields": "status_code,status", "access_token": tok})
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED") or time.time() > deadline:
            raise RuntimeError(f"Container: {s.get('status')}")
        time.sleep(10)
    if dry:
        return None, "DRY-RUN: upload ed elaborazione ok, non pubblicato"
    mid = req("POST", f"{API}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok})["id"]
    info = req("GET", f"{API}/{mid}", {"fields": "permalink", "access_token": tok})
    return mid, info.get("permalink")


def main():
    test = os.environ.get("DRY_TEST", "").strip()
    if test:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=5",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "5", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "test.mp4"], check=True)
        for prof in test.split(","):
            try:
                publish(prof.strip(), "test.mp4", "test", dry=True); print("dry ok")
            except Exception as e:
                print("dry FAIL")
        return
    # Repo pubblico = minuti gratis: la run aspetta il prossimo post e prima di scadere passa il testimone
    # a una nuova run (catena). Il cron ogni 5 minuti resta come riserva.
    started = time.time()
    while True:
        run_once()
        commit()
        nxt = next_due()
        if nxt is None:
            print("Coda vuota.")
            return
        wait = (nxt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        left = 320 * 60 - (time.time() - started)
        if wait > left:
            time.sleep(max(left, 0))
            subprocess.run(["gh", "workflow", "run", "publish.yml"], check=False)
            print("Catena: nuova run lanciata.")
            return
        time.sleep(max(wait, 0) + 5)
        subprocess.run(["git", "pull", "-q", "--rebase"], check=False)


def pending():
    out = []
    for p in sorted(glob.glob("queue/*.json")):
        it = json.load(open(p, encoding="utf-8"))  # status/orario sono in chiaro
        if it.get("status") == "pending":
            out.append((datetime.datetime.fromisoformat(it["publish_at_utc"]), p, it))
    return sorted(out, key=lambda x: x[0])


def next_due():
    now = datetime.datetime.now(datetime.timezone.utc)
    fut = [at for at, _, _ in pending() if at > now]
    return fut[0] if fut else None


def commit():
    subprocess.run(["git", "config", "user.name", "ig-scheduler-bot"], check=False)
    subprocess.run(["git", "config", "user.email", "ig-scheduler-bot@users.noreply.github.com"], check=False)
    subprocess.run(["git", "add", "queue"], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m", "queue: update status"], check=False)
        subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
        subprocess.run(["git", "push", "-q"], check=False)


def cron_ok():
    """True se il cron di GitHub ha girato nelle ultime 6 ore: allora la catena (che costa minuti) non serve."""
    r = subprocess.run(["gh", "run", "list", "--event", "schedule", "-L", "1", "--json", "createdAt", "-q", ".[0].createdAt"],
                       capture_output=True, text=True).stdout.strip()
    if not r:
        return False
    t = datetime.datetime.fromisoformat(r.replace("Z", "+00:00"))
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() < 6 * 3600


def claim(p):
    """Lock tra run parallele: segna 'publishing' e fa push. Se il push viene rifiutato, un'altra run l'ha preso."""
    subprocess.run(["git", "config", "user.name", "ig-scheduler-bot"], check=False)
    subprocess.run(["git", "config", "user.email", "ig-scheduler-bot@users.noreply.github.com"], check=False)
    subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
    raw = json.load(open(p, encoding="utf-8"))
    if raw.get("status") != "pending":
        return False
    raw["status"] = "publishing"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    subprocess.run(["git", "add", p], check=False)
    subprocess.run(["git", "commit", "-q", "-m", f"claim {os.path.basename(p)}"], check=False)
    if subprocess.run(["git", "push", "-q"]).returncode != 0:
        subprocess.run(["git", "reset", "-q", "--hard", "@{u}"], check=False)
        subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
        return False
    return True


def run_once():
    now = datetime.datetime.now(datetime.timezone.utc)
    for at, p, it in pending():
        if at > now:
            continue
        if (now - at).total_seconds() > MAX_LATE_H * 3600:
            it = qcrypt.load(p)
            it.update(status="late", error=f"oltre {MAX_LATE_H}h di ritardo, non pubblicato")
        else:
            if not claim(p):
                print(f"SKIP {os.path.basename(p)}: già preso da un'altra run")
                continue
            it = qcrypt.load(p)
            name = os.path.basename(p)[:-5]
            try:
                subprocess.run(["gh", "release", "download", "queue", "-p", it["asset"], "-O", "video.bin", "--clobber"],
                               check=True, capture_output=True)
                qcrypt.dec_file("video.bin", "video.mp4")
                mid, link = publish(it["profile"], "video.mp4", it["caption"])
                it.update(status="published", media_id=mid, permalink=link, published_at_utc=now.isoformat())
                subprocess.run(["gh", "release", "delete-asset", "queue", it["asset"], "-y"], check=False, capture_output=True)
                print(f"OK {name}")  # log pubblici: niente profilo, link o errori in chiaro
            except Exception as e:
                it.update(status="failed", error=str(e)[:500])
                print(f"FAIL {name} (dettagli cifrati nella coda)")
            for f in ("video.bin", "video.mp4"):
                if os.path.exists(f):
                    os.remove(f)
        qcrypt.save(p, it)


if __name__ == "__main__":
    main()
