"""Riserva locale (PC acceso): se in coda c'e' un post 'pending' gia' scaduto, lancia subito il workflow.
Lanciato ogni 5 minuti da Task Scheduler. Non consuma minuti GitHub se non c'e' niente da pubblicare.
Il cron di GitHub resta attivo per quando il PC e' spento.
"""
import datetime, glob, json, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
GH = r"C:\Program Files\GitHub CLI\gh.exe"
subprocess.run(["git", "-C", HERE, "pull", "-q", "--rebase"], capture_output=True)
now = datetime.datetime.now(datetime.timezone.utc)
due = False
for p in glob.glob(os.path.join(HERE, "queue", "*.json")):
    it = json.load(open(p, encoding="utf-8"))  # status in chiaro
    if it.get("status") == "pending":
        late = (now - datetime.datetime.fromisoformat(it["publish_at_utc"])).total_seconds()
        if 0 <= late < 6 * 3600:
            due = True
if due:
    running = subprocess.run([GH, "run", "list", "-R", "Bellum-Exe/scheduler-q", "-s", "in_progress", "--json", "databaseId", "-q", "length"],
                             capture_output=True, text=True).stdout.strip()
    queued = subprocess.run([GH, "run", "list", "-R", "Bellum-Exe/scheduler-q", "-s", "queued", "--json", "databaseId", "-q", "length"],
                            capture_output=True, text=True).stdout.strip()
    if running in ("", "0") and queued in ("", "0"):
        subprocess.run([GH, "workflow", "run", "publish.yml", "-R", "Bellum-Exe/scheduler-q"])
