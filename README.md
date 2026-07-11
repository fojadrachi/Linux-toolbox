# Linux Toolbox

Eine kleine native GTK4/libadwaita-App, die alle wichtigen Systeminfos und
Wartungsaufgaben an einem Ort bündelt — für Fedora-, Debian/Ubuntu-, Arch-
und openSUSE-basierte Distributionen (Fedora, Fedora KDE, BlossomOS,
Bazzite, Nobara, Ubuntu, Debian, Linux Mint, Pop!_OS, Arch, Manjaro,
EndeavourOS, openSUSE Tumbleweed/Leap, ...).

Die Update-Prüfung erkennt automatisch den vorhandenen Paketmanager
(`dnf`/`dnf5`, `apt`/`apt-get`, `pacman`, `zypper`) und passt sich
entsprechend an. Alle anderen Funktionen (Hardware, NVIDIA, Speicher,
Dienste, Gaming) basieren auf generischen Linux-Schnittstellen und
funktionieren distro-unabhängig.

## Funktionen

- ✅ **Hardwareübersicht** — CPU, GPU, RAM, Mainboard, Kernel, Desktop
- ✅ **NVIDIA-Erkennung** — Treiberversion, Wayland/X11, Vulkan, OpenGL
- ✅ **Speicher** — SSD/HDD-Auslastung pro Mountpoint, SMART-Status (optional, root)
- ✅ **Updates** — automatische Paketmanager-Erkennung (dnf, apt, pacman,
  zypper), verfügbare Updates, Flatpak-Updates, Ein-Klick-Aktualisieren
- ✅ **Dienste** — Docker, Podman, Steam, SSH, Tailscale
- ✅ **Gaming** — MangoHud, Gamescope, Gamemode, Proton-GE, Wine-Version
- ✅ **Ein-Klick-Kopieren** — kopiert einen kompletten Support-Bericht in die
  Zwischenablage, ideal für Reddit oder Distro-Foren

Beispiel-Bericht:

```
Fedora 44 KDE
Kernel: 6.18
CPU: Ryzen 5 5600
GPU: RTX 2060
Treiber: 610.43.02
Session: Wayland
RAM: 16 GB
Paketmanager: DNF
Updates: 12 Update(s) verfügbar
Flatpaks: 3 Flatpak-Update(s) verfügbar
Steam: installiert (nativ)
```

## Installation

### Variante 1: Installationsskript (empfohlen)

```bash
chmod +x install.sh
./install.sh
```

Das Skript erkennt den vorhandenen Paketmanager (`dnf`, `apt`, `pacman`
oder `zypper`) und installiert fehlende Systempakete automatisch, kopiert
die App nach `~/.local/share/linux-toolbox`, legt einen Starter unter
`~/.local/bin/linux-toolbox` an und registriert einen Eintrag im
Anwendungsmenü inkl. Icon. Eine vorhandene ältere "Fedora Toolbox"-
Installation wird dabei automatisch bereinigt.

Deinstallieren:

```bash
./install.sh --uninstall
```

### Variante 2: Manuell mit pip

```bash
# Fedora
sudo dnf install python3-gobject gtk4 libadwaita
# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
# Arch Linux
sudo pacman -S python-gobject gtk4 libadwaita
# openSUSE
sudo zypper install python3-gobject gtk4 libadwaita

pip install --user .
linux-toolbox
```

### Variante 3: Direkt aus dem Quellordner starten (ohne Installation)

```bash
# Abhängigkeiten wie oben installieren, dann:
python3 -m linux_toolbox
```

## Voraussetzungen

- Python ≥ 3.10
- GTK4 + libadwaita mit GObject-Introspection (Paketname je nach Distro
  unterschiedlich, siehe oben — auf vielen Distros bereits vorinstalliert)
- Optionale Tools für vollständige Daten: `nvidia-smi` (NVIDIA-Treiber),
  `vulkaninfo` (Paket `vulkan-tools`), `glxinfo` (Paket `mesa-demos` /
  `glx-utils` / `mesa-utils`), `smartmontools` für SMART-Status (benötigt
  root), `pacman-contrib` unter Arch für eine root-lose Update-Prüfung via
  `checkupdates`

Fehlt ein Tool, zeigt die App das transparent an (z. B. "vulkaninfo nicht
installiert") statt abzustürzen — es ist also nicht nötig, alle optionalen
Pakete zu installieren.

## Unterstützte Paketmanager

| Paketmanager | Distros (Beispiele)              | Update-Prüfung                          | Ein-Klick-Update                  |
|--------------|-----------------------------------|------------------------------------------|-------------------------------------|
| dnf / dnf5   | Fedora, Nobara, Bazzite            | `dnf check-update`                       | `pkexec dnf upgrade -y`             |
| apt          | Debian, Ubuntu, Mint, Pop!_OS      | `apt-get -s upgrade` (Simulation)        | `pkexec apt-get update && upgrade`  |
| pacman       | Arch, Manjaro, EndeavourOS         | `checkupdates` (falls installiert), sonst `pacman -Qu` | `pkexec pacman -Syu --noconfirm` |
| zypper       | openSUSE Tumbleweed/Leap           | `zypper list-updates`                    | `pkexec zypper update`              |

Wird kein unterstützter Paketmanager gefunden, zeigt die App das
transparent an und deaktiviert den entsprechenden Update-Button — der
Rest der App funktioniert unverändert weiter.

**Hinweis zu apt:** Ohne root-Rechte kann die App den lokalen Paket-Index
nicht aktualisieren, bevor sie die Update-Anzahl berechnet. Die Anzeige
kann daher veraltet sein, bis der Index (z. B. über den "Pakete
aktualisieren"-Button, der `apt update` vorab ausführt) neu geladen wurde.

**Hinweis zu pacman:** Für eine root-lose und stets aktuelle Update-Prüfung
wird das Paket `pacman-contrib` (liefert `checkupdates`) empfohlen. Ohne
dieses Paket wird gegen die zuletzt synchronisierte lokale Datenbank
geprüft, was veraltet sein kann.

## Architektur

```
linux_toolbox/
├── __init__.py       Paket-Metadaten
├── __main__.py        Einstiegspunkt für `python -m linux_toolbox`
├── pkgmanager.py       Paketmanager-Abstraktion (dnf/apt/pacman/zypper),
│                        keine GTK-Abhängigkeit, einzeln testbar
├── sysinfo.py          Reine Datensammlung (keine GTK-Abhängigkeit,
│                        einzeln testbar), defensiv gegen fehlende
│                        Tools/Rechte/Timeouts
└── main.py             GTK4/libadwaita-Oberfläche, ruft sysinfo.py aus
                          Hintergrund-Threads auf (UI blockiert nie)
```

- Schnelle Daten (Hardware, NVIDIA, Speicher, Dienste, Gaming) werden beim
  Start und bei "Neu laden" in einem Hintergrund-Thread gesammelt.
- Langsame Daten (Paketmanager-Updates, Flatpak-Updates) laufen separat,
  damit sie die restliche Anzeige nicht verzögern.
- "Ein Klick zum Aktualisieren" ruft je nach erkanntem Paketmanager den
  passenden Befehl über `pkexec` auf (z. B. `dnf upgrade -y`, `apt-get
  upgrade -y`, `pacman -Syu`, `zypper update`) bzw. `flatpak update -y` —
  `pkexec` zeigt dabei die normale PolicyKit-Passwortabfrage.

## Bekannte Einschränkungen

- Mainboard-Name und SMART-Status benötigen teils root-Rechte
  (`/sys/class/dmi/id/*` ist meist ohne root lesbar, SMART über `smartctl`
  nicht).
- Die Paket-Update-Prüfung kann je nach Distro und Metadaten-Cache ein
  paar Sekunden dauern — läuft deshalb immer asynchron.
- Andere Paketmanager (z. B. `apk` auf Alpine, `xbps` auf Void, `eopkg` auf
  Solus) werden aktuell nicht unterstützt; die App zeigt das transparent
  an, statt abzustürzen. Der Rest der App funktioniert auf jeder
  Linux-Distribution mit systemd, GTK4 und libadwaita.

## Lizenz

MIT — siehe `LICENSE`.
