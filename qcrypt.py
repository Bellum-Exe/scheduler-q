"""Cifratura AES-256 (openssl) per coda e video: il repo e' pubblico, il contenuto no.
Chiave: variabile QUEUE_KEY (Secret su GitHub) oppure file locale .queue_key (mai committato).
"""
import base64, json, os, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OPENSSL = shutil.which("openssl") or r"C:\Program Files\Git\mingw64\bin\openssl.exe"


def key():
    k = os.environ.get("QUEUE_KEY")
    if not k:
        k = open(os.path.join(HERE, ".queue_key"), encoding="utf-8").read().strip()
    return k


def _ssl(args, data):
    env = dict(os.environ, QUEUE_KEY=key())
    r = subprocess.run([OPENSSL, "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000", *args, "-pass", "env:QUEUE_KEY"],
                       input=data, capture_output=True, env=env)
    if r.returncode:
        raise RuntimeError("openssl: " + r.stderr.decode(errors="replace")[:200])
    return r.stdout


def enc_bytes(b):
    return _ssl([], b)


def dec_bytes(b):
    return _ssl(["-d"], b)


def enc_obj(o):
    return base64.b64encode(enc_bytes(json.dumps(o, ensure_ascii=False).encode())).decode()


def dec_obj(s):
    return json.loads(dec_bytes(base64.b64decode(s)).decode())


def enc_file(src, dst):
    open(dst, "wb").write(enc_bytes(open(src, "rb").read()))


def dec_file(src, dst):
    open(dst, "wb").write(dec_bytes(open(src, "rb").read()))


# Formato file in queue/: {"publish_at_utc", "status", "data": <cifrato {profile, asset, caption, source}>,
#                          "result": <cifrato {media_id, permalink, error, ...}>}
def load(p):
    raw = json.load(open(p, encoding="utf-8"))
    it = dict(dec_obj(raw["data"]))
    if raw.get("result"):
        it.update(dec_obj(raw["result"]))
    it["publish_at_utc"], it["status"] = raw["publish_at_utc"], raw["status"]
    return it


PRIVATE = ("profile", "asset", "caption", "source")


def save(p, it):
    raw = {"publish_at_utc": it["publish_at_utc"], "status": it["status"],
           "data": enc_obj({k: it.get(k) for k in PRIVATE})}
    rest = {k: v for k, v in it.items() if k not in PRIVATE + ("publish_at_utc", "status")}
    if rest:
        raw["result"] = enc_obj(rest)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
