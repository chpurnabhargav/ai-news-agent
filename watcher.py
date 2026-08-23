import datetime
import os
import socket
import subprocess
import sys
import time

import db
import fetcher

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(os.path.dirname(db.DB_PATH), "last_run.txt")
CHECK_INTERVAL = 300


def is_online():
    for host in ("8.8.8.8", "1.1.1.1", "208.67.222.222"):
        try:
            socket.create_connection((host, 53), timeout=5).close()
            return True
        except OSError:
            continue
    return False


def already_run_today():
    if not os.path.exists(MARKER):
        return False
    with open(MARKER, "r", encoding="utf-8") as f:
        return f.read().strip() == datetime.date.today().isoformat()


def mark_today():
    os.makedirs(os.path.dirname(MARKER), exist_ok=True)
    with open(MARKER, "w", encoding="utf-8") as f:
        f.write(datetime.date.today().isoformat())


def open_app():
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    subprocess.Popen([pythonw, os.path.join(BASE_DIR, "app.py")])


def main():
    while True:
        if is_online():
            if not already_run_today():
                try:
                    db.init_db()
                    new = fetcher.fetch_all()
                    open_app()
                    mark_today()
                    print(f"{datetime.datetime.now()}: fetched {new} new, app shown")
                except Exception as e:
                    print(f"{datetime.datetime.now()}: error, will retry: {e}")
            else:
                time.sleep(3600)
                continue
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
