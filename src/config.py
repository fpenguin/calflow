import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "data")
SECRETS_DIR = os.path.join(BASE_DIR, "secrets")

os.makedirs(DATA_DIR, exist_ok=True)

TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
STATE_FILE = os.path.join(DATA_DIR, "opened_events.json")
LOG_FILE = os.path.join(DATA_DIR, "run.log")

CREDENTIALS_FILE = os.path.join(SECRETS_DIR, "credentials.json")
