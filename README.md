# scheduler-q

Coda di pubblicazione che gira su GitHub Actions. Coda e video sono cifrati (AES-256) con una chiave che sta solo nei Secrets e in un file locale non committato.

- `python enqueue.py <profilo> VIDEO.mp4`: mette il video in coda nel primo slot libero.
- `python enqueue.py list`: mostra lo stato della coda (serve la chiave locale `.queue_key`).
