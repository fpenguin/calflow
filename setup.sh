#!/bin/bash

echo "Setting up Calflow..."

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p data

echo ""
echo "✅ Setup complete"
echo "👉 Place credentials.json in src/"
echo "👉 Then run: ./run.sh"