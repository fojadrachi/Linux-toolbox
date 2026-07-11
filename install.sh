#!/usr/bin/env bash
# install.sh — Installiert Linux Toolbox lokal für den aktuellen Benutzer.
#
# Unterstützt die automatische Installation der Systemabhängigkeiten über
# dnf (Fedora), apt (Debian/Ubuntu), pacman (Arch) und zypper (openSUSE).
# Auf anderen Distributionen bitte die GTK4/libadwaita-Python-Bindings
# manuell installieren (siehe README.md).
#
# Nutzung:
#   chmod +x install.sh
#   ./install.sh
#
# Deinstallieren:
#   ./install.sh --uninstall

set -euo pipefail

APP_DIR="$HOME/.local/share/linux-toolbox"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Alte Installationspfade/-namen aus der früheren "Fedora Toolbox"-Version
OLD_APP_DIR="$HOME/.local/share/fedora-toolbox"
OLD_BIN="$BIN_DIR/fedora-toolbox"
OLD_DESKTOP="$DESKTOP_DIR/de.fojadrachi.FedoraToolbox.desktop"
OLD_ICON="$ICON_DIR/de.fojadrachi.FedoraToolbox.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Entferne Linux Toolbox ..."
    rm -rf "$APP_DIR" "$OLD_APP_DIR"
    rm -f "$BIN_DIR/linux-toolbox" "$OLD_BIN"
    rm -f "$DESKTOP_DIR/de.fojadrachi.LinuxToolbox.desktop" "$OLD_DESKTOP"
    rm -f "$ICON_DIR/de.fojadrachi.LinuxToolbox.svg" "$OLD_ICON"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    echo "Fertig. Linux Toolbox wurde deinstalliert."
    exit 0
fi

echo "== Linux Toolbox Installation =="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Fehler: python3 wurde nicht gefunden." >&2
    exit 1
fi

# GTK4/libadwaita-Python-Bindings prüfen und ggf. via erkanntem
# Paketmanager installieren.
if python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw" 2>/dev/null; then
    echo "GTK4/libadwaita Python-Bindings bereits vorhanden."
elif command -v dnf >/dev/null 2>&1; then
    echo "-- Fedora erkannt: Installiere Abhängigkeiten via dnf (benötigt sudo) --"
    sudo dnf install -y python3-gobject gtk4 libadwaita
elif command -v apt-get >/dev/null 2>&1 || command -v apt >/dev/null 2>&1; then
    echo "-- Debian/Ubuntu erkannt: Installiere Abhängigkeiten via apt (benötigt sudo) --"
    APT_BIN="apt-get"
    command -v apt-get >/dev/null 2>&1 || APT_BIN="apt"
    sudo "$APT_BIN" update
    sudo "$APT_BIN" install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
elif command -v pacman >/dev/null 2>&1; then
    echo "-- Arch Linux erkannt: Installiere Abhängigkeiten via pacman (benötigt sudo) --"
    sudo pacman -S --needed --noconfirm python-gobject gtk4 libadwaita
elif command -v zypper >/dev/null 2>&1; then
    echo "-- openSUSE erkannt: Installiere Abhängigkeiten via zypper (benötigt sudo) --"
    sudo zypper --non-interactive install python3-gobject gtk4 libadwaita
else
    echo "Hinweis: Kein unterstützter Paketmanager (dnf/apt/pacman/zypper) gefunden."
    echo "Bitte installiere die GTK4/libadwaita Python-Bindings manuell — siehe README.md."
fi

echo "-- Kopiere Anwendungsdateien nach $APP_DIR --"
mkdir -p "$APP_DIR"
cp -r "$SCRIPT_DIR/linux_toolbox" "$APP_DIR/"

echo "-- Erstelle Startskript in $BIN_DIR --"
mkdir -p "$BIN_DIR"
# PYTHONPATH-Wrapper, damit das App-Modul unabhängig vom Arbeitsverzeichnis gefunden wird
cat > "$BIN_DIR/linux-toolbox" << EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR:\${PYTHONPATH:-}"
exec python3 -m linux_toolbox "\$@"
EOF
chmod +x "$BIN_DIR/linux-toolbox"

echo "-- Installiere Desktop-Icon und Launcher-Eintrag --"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
cp "$SCRIPT_DIR/data/de.fojadrachi.LinuxToolbox.desktop" "$DESKTOP_DIR/"
cp "$SCRIPT_DIR/data/de.fojadrachi.LinuxToolbox.svg" "$ICON_DIR/"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# Alte "Fedora Toolbox"-Installation aufräumen, falls vorhanden
if [[ -d "$OLD_APP_DIR" || -f "$OLD_BIN" || -f "$OLD_DESKTOP" ]]; then
    echo "-- Entferne alte Fedora-Toolbox-Installation --"
    rm -rf "$OLD_APP_DIR"
    rm -f "$OLD_BIN" "$OLD_DESKTOP" "$OLD_ICON"
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo
    echo "HINWEIS: $BIN_DIR ist noch nicht in deinem PATH."
    echo "Füge folgende Zeile zu ~/.bashrc oder ~/.zshrc hinzu:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo
echo "Installation abgeschlossen!"
echo "Starten mit:  linux-toolbox"
echo "Oder über das Anwendungsmenü: 'Linux Toolbox'"
