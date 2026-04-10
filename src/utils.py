from settings import LOG_MODE
from datetime import datetime
import os

LOG_FILE = "/tmp/calflow.log"


def log(message):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{timestamp} {message}"

    if LOG_MODE in ["console", "both"]:
        print(line)

    if LOG_MODE in ["file", "both"]:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")