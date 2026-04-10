#!/usr/bin/env bash

set -e

echo "🚀 Installing Calflow..."

# Install directory
INSTALL_DIR="$HOME/.calflow"

echo "📦 Cloning repository..."
rm -rf "$INSTALL_DIR"
git clone https://github.com/fpenguin/calflow.git "$INSTALL_DIR"

cd "$INSTALL_DIR"

echo "🐍 Setting up virtual environment..."
python3 -m venv .venv

echo "📦 Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "🔧 Creating shortcut..."

mkdir -p "$HOME/.local/bin"

cat <<EOF > "$HOME/.local/bin/calflow"
#!/usr/bin/env bash
source "$INSTALL_DIR/.venv/bin/activate"
python "$INSTALL_DIR/src/main.py" "\$@"
EOF

chmod +x "$HOME/.local/bin/calflow"

echo "🔗 Adding to PATH (if needed)..."

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
    echo "⚠️ Restart terminal or run: source ~/.zshrc"
fi

echo ""
echo "✅ Calflow installed!"
echo ""
echo "Run setup:"
echo "   calflow --setup"
echo ""