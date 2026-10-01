"""Availability probe: hit /readyz every --interval seconds and report uptime %.

Run it while you roll the backend Deployment, kill pods, or drive the HPA with load:
  python scripts/uptime_probe.py --url http://analytics.local --minutes 30
  kubectl -n analytics rollout restart deploy/backend      # in another terminal
  kubectl -n analytics delete pod -l app=backend --wait=false
"""
import argparse
import time
import urllib.request


def main(a):
    ok = total = 0
    end = time.time() + a.minutes * 60
    while time.time() < end:
        total += 1
        try:
            with urllib.request.urlopen(f"{a.url}/readyz", timeout=2) as r:
                ok += r.status == 200
        except Exception as exc:
            print(time.strftime("%H:%M:%S"), "DOWN", exc)
        if total % 60 == 0:
            print(f"{time.strftime('%H:%M:%S')} uptime {100 * ok / total:.2f}% ({ok}/{total})")
        time.sleep(a.interval)
    print(f"FINAL uptime {100 * ok / total:.3f}% over {total} probes")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:5000")
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--interval", type=float, default=1)
    main(p.parse_args())
