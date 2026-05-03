#!/bin/bash
# CalFlow local setup (v2.0).
#
# Run from a freshly cloned repo:
#     ./scripts/setup.sh
#
# What it does:
#   1. creates a virtualenv (.venv)
#   2. installs Python deps from requirements.txt
#   3. ensures data/ and secrets/ exist
#
# After this, place credentials.json into secrets/ and run:
#     source .venv/bin/activate
#     python3 -m cli.main setup

set -e

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "✅ Virtualenv created"
else
  echo "ℹ️  Virtualenv already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data
mkdir -p secrets

cat <<'EOF'

✅ CalFlow setup complete.

Next steps:

1. Place your Google OAuth client JSON at:
       secrets/credentials.json
   (Console → APIs & Services → Credentials → OAuth Client ID → Desktop app)

2. Run onboarding (OAuth + calendar selection + optional daemon install):
       source .venv/bin/activate
       python3 -m cli.main setup

3. Try the REPL while you wait for an event:
       python3 -m cli.repl
EOF
