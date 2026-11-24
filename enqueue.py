"""Uso locale (agenti): mette in coda un reel su GitHub.
  python enqueue.py <profilo> VIDEO.mp4 [--caption-file F.txt] [--at "2026-11-22 19:00"]   (orario New York)
  python enqueue.py list
  python enqueue.py cancel VIDEO_SORGENTE.mp4 [--at PROFILO]   (annulla i post pending di quel video)
Senza --at usa il primo slot libero dal giorno dopo (data NY): 19:00 e 21:30 America/New_York.
Toglie i metadati, carica il video come asset della release 'queue', crea queue/<id>.json e fa push.
Dopo il push il PC puo' restare spento: pubblica GitHub Actions.
"""
import argparse, datetime, glob, json, os, secrets, subprocess, sys, tempfile
import qcrypt
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
NY, IT, UTC = ZoneInfo("America/New_York"), ZoneInfo("Europe/Rome"), datetime.timezone.utc
# Profili e slot in profiles.json (locale, non committato): nome -> {"id": alias dei Secrets, "slots": [[h, m], ...]}
PROF = json.load(open(os.path.join(HERE, "profiles.json"), encoding="utf-8"))
SLOTS = {k: [tuple(x) for x in v["slots"]] for k, v in PROF.items()}
GH = r"C:\Program Files\GitHub CLI\gh.exe"


def git(*a):
    subprocess.run(["git", "-C", HERE, *a], check=True)


def taken(profile):
    out = set()
    for p in glob.glob(os.path.join(HERE, "queue", "*.json")):
        it = qcrypt.load(p)
        if it["profile"] == profile and it["status"] in ("pending", "published"):
            out.add(it["publish_at_utc"])
    return out


def next_slot(profile):
    used = taken(profile)
    day = datetime.datetime.now(NY).date() + datetime.timedelta(days=1)
    while True:
        for h, m in SLOTS[profile]:
            t = datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=NY).astimezone(UTC).isoformat()
            if t not in used:
                return t
        day += datetime.timedelta(days=1)


def fmt(utc_iso):
    t = datetime.datetime.fromisoformat(utc_iso)
    return f"{t.astimezone(NY):%a %d/%m %H:%M} NY = {t.astimezone(IT):%a %d/%m %H:%M} IT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("video", nargs="?")
    ap.add_argument("--caption-file")
    ap.add_argument("--at")
    a = ap.parse_args()
    git("pull", "-q", "--rebase")
    if a.profile == "cancel":
        # python enqueue.py cancel NOME_VIDEO_SORGENTE [--profile-name micky]
        n = 0
        for p in sorted(glob.glob(os.path.join(HERE, "queue", "*.json"))):
            it = qcrypt.load(p)
            if it["status"] == "pending" and it.get("source") == a.video and (not a.at or it["profile"] == a.at):
                it.update(status="cancelled", error="annullato a mano")
                qcrypt.save(p, it)
                n += 1
                print(f"ANNULLATO {it['source']} ({it['profile']}) {fmt(it['publish_at_utc'])}")
        if n:
            git("add", "queue")
            git("commit", "-q", "-m", "queue: update")
            git("push", "-q")
        else:
            print("Nessun post pending con quel nome.")
        return
    if a.profile == "list":
        for p in sorted(glob.glob(os.path.join(HERE, "queue", "*.json"))):
            it = qcrypt.load(p)
            print(f"{it.get('source') or os.path.basename(p)[:-5]}  {it['profile']:7} {it['status']:9} {fmt(it['publish_at_utc'])}  {it.get('permalink') or it.get('error') or ''}")
        return
    if a.profile not in PROF or not a.video:
        sys.exit("profilo: " + ", ".join(PROF) + "; serve il video")
    capf = a.caption_file or os.path.splitext(a.video)[0] + ".txt"
    caption = open(capf, encoding="utf-8-sig").read() if os.path.exists(capf) else ""
    caption = "\n".join(l for l in caption.splitlines() if not l.strip().lower().startswith("note:")).strip()
    if a.at:
        when = datetime.datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=NY).astimezone(UTC).isoformat()
    else:
        when = next_slot(a.profile)
    qid = secrets.token_hex(8)  # nome casuale: il repo e' pubblico
    asset = secrets.token_hex(8) + ".bin"
    tmp = os.path.join(tempfile.gettempdir(), qid + ".mp4")
    clean = os.path.join(tempfile.gettempdir(), asset)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-map_metadata", "-1", "-c", "copy", tmp], check=True)
    qcrypt.enc_file(tmp, clean)
    os.remove(tmp)
    if subprocess.run([GH, "release", "view", "queue"], cwd=HERE, capture_output=True).returncode != 0:
        subprocess.run([GH, "release", "create", "queue", "--title", "queue", "--notes", "video in coda"], cwd=HERE, check=True)
    subprocess.run([GH, "release", "upload", "queue", clean, "--clobber"], cwd=HERE, check=True)
    os.remove(clean)
    item = {"profile": a.profile, "asset": asset, "caption": caption, "publish_at_utc": when,
            "status": "pending", "source": os.path.basename(a.video)}
    qcrypt.save(os.path.join(HERE, "queue", qid + ".json"), item)
    git("add", "queue")
    git("commit", "-q", "-m", "enqueue")
    git("push", "-q")
    subprocess.run([GH, "workflow", "run", "publish.yml"], cwd=HERE, check=False, capture_output=True)
    print(f"IN CODA {os.path.basename(a.video)} ({qid}): {fmt(when)}")


if __name__ == "__main__":
    main()
