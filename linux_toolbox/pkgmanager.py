"""
pkgmanager.py — Paketmanager-Abstraktion für Linux Toolbox.

Erkennt beim Start, welcher Paketmanager auf dem System vorhanden ist
(dnf/dnf5, apt/apt-get, pacman, zypper) und bietet dafür einheitliche
Funktionen zum Prüfen und Installieren von Updates an.

Wie in sysinfo.py gilt: keine Funktion darf abstürzen. Fehlt ein
Paketmanager, fehlende Rechte oder Timeouts liefern immer einen
sprechenden String zurück statt eine Exception zu werfen.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

TIMEOUT_CHECK = 30  # Sekunden für Update-Prüfungen
TIMEOUT_UPGRADE = 900  # Sekunden für den eigentlichen Upgrade-Lauf

NA = "n/a"


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


@dataclass
class PackageManager:
    """Beschreibt einen unterstützten Paketmanager und seine Aufrufe."""

    id: str  # interner Name, z. B. "dnf", "apt", "pacman", "zypper"
    display_name: str  # Anzeigename, z. B. "DNF", "APT", "Pacman", "Zypper"

    def check_updates(self) -> str:
        raise NotImplementedError

    def upgrade(self) -> tuple[bool, str]:
        raise NotImplementedError


class DnfManager(PackageManager):
    def __init__(self) -> None:
        binary = "dnf5" if _which("dnf5") else "dnf"
        super().__init__(id="dnf", display_name="DNF")
        self.binary = binary

    def check_updates(self) -> str:
        result = _run([self.binary, "check-update", "--quiet"], TIMEOUT_CHECK)
        if result is None:
            return "Fehler beim Prüfen (Timeout/keine Berechtigung)"
        # dnf check-update: Exit-Code 0 = keine Updates, 100 = Updates vorhanden, 1 = Fehler
        if result.returncode == 1:
            return "Fehler beim Prüfen"
        lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith(("Last metadata", "Obsoleting"))
        ]
        if result.returncode == 0:
            return "System aktuell (0 Updates)"
        return f"{len(lines)} Update(s) verfügbar"

    def upgrade(self) -> tuple[bool, str]:
        if not _which("pkexec"):
            return False, f"pkexec nicht verfügbar — bitte manuell 'sudo {self.binary} upgrade' ausführen"
        result = _run(["pkexec", self.binary, "upgrade", "-y"], TIMEOUT_UPGRADE)
        if result is None:
            return False, "Fehler oder Timeout beim Update"
        if result.returncode == 0:
            return True, "Update erfolgreich abgeschlossen"
        return False, (result.stderr or result.stdout or "Unbekannter Fehler").strip()[:500]


class AptManager(PackageManager):
    def __init__(self) -> None:
        super().__init__(id="apt", display_name="APT")
        self.binary = "apt-get" if _which("apt-get") else "apt"

    def check_updates(self) -> str:
        # '-s' (simulate) berechnet die anstehenden Updates gegen den
        # vorhandenen lokalen Paket-Cache, ohne root-Rechte zu benötigen.
        # Hinweis: 'apt-get update' läuft davor NICHT automatisch (würde
        # meist root-Rechte erfordern) — die Liste kann daher veraltet
        # sein, falls der Paket-Index lange nicht aktualisiert wurde.
        result = _run([self.binary, "-s", "upgrade"], TIMEOUT_CHECK)
        if result is None:
            return "Fehler beim Prüfen (Timeout/keine Berechtigung)"
        if result.returncode != 0:
            return "Fehler beim Prüfen"
        count = sum(1 for line in result.stdout.splitlines() if line.startswith("Inst "))
        if count == 0:
            return "System aktuell (0 Updates, ggf. veralteter Index)"
        return f"{count} Update(s) verfügbar"

    def upgrade(self) -> tuple[bool, str]:
        if not _which("pkexec"):
            return False, "pkexec nicht verfügbar — bitte manuell 'sudo apt update && sudo apt upgrade' ausführen"
        update_result = _run(["pkexec", self.binary, "update"], TIMEOUT_UPGRADE)
        if update_result is None or update_result.returncode != 0:
            msg = (update_result.stderr if update_result else None) or "Fehler bei 'apt update'"
            return False, msg.strip()[:500]
        result = _run(["pkexec", self.binary, "upgrade", "-y"], TIMEOUT_UPGRADE)
        if result is None:
            return False, "Fehler oder Timeout beim Update"
        if result.returncode == 0:
            return True, "Update erfolgreich abgeschlossen"
        return False, (result.stderr or result.stdout or "Unbekannter Fehler").strip()[:500]


class PacmanManager(PackageManager):
    def __init__(self) -> None:
        super().__init__(id="pacman", display_name="Pacman")
        # 'checkupdates' (aus pacman-contrib) prüft gegen eine separate
        # Sync-DB und braucht dafür keine root-Rechte — falls vorhanden,
        # ist das der zuverlässigere Weg.
        self.has_checkupdates = _which("checkupdates") is not None

    def check_updates(self) -> str:
        if self.has_checkupdates:
            result = _run(["checkupdates"], TIMEOUT_CHECK)
            if result is None:
                return "Fehler beim Prüfen (Timeout/keine Berechtigung)"
            # checkupdates: Exit-Code 2 = keine Updates, kein Fehler
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            if not lines:
                return "System aktuell (0 Updates)"
            return f"{len(lines)} Update(s) verfügbar"
        # Fallback: 'pacman -Qu' prüft gegen die zuletzt synchronisierte
        # lokale Datenbank (kann veraltet sein, wenn 'pacman -Sy' schon
        # eine Weile nicht mehr lief).
        result = _run(["pacman", "-Qu"], TIMEOUT_CHECK)
        if result is None:
            return "Fehler beim Prüfen (Timeout/keine Berechtigung)"
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "System aktuell (0 Updates, ggf. veralteter Index — 'pacman-contrib' installieren für genauere Prüfung)"
        return f"{len(lines)} Update(s) verfügbar"

    def upgrade(self) -> tuple[bool, str]:
        if not _which("pkexec"):
            return False, "pkexec nicht verfügbar — bitte manuell 'sudo pacman -Syu' ausführen"
        result = _run(["pkexec", "pacman", "-Syu", "--noconfirm"], TIMEOUT_UPGRADE)
        if result is None:
            return False, "Fehler oder Timeout beim Update"
        if result.returncode == 0:
            return True, "Update erfolgreich abgeschlossen"
        return False, (result.stderr or result.stdout or "Unbekannter Fehler").strip()[:500]


class ZypperManager(PackageManager):
    def __init__(self) -> None:
        super().__init__(id="zypper", display_name="Zypper")

    def check_updates(self) -> str:
        result = _run(["zypper", "--non-interactive", "list-updates"], TIMEOUT_CHECK)
        if result is None:
            return "Fehler beim Prüfen (Timeout/keine Berechtigung)"
        if result.returncode not in (0, 100):
            return "Fehler beim Prüfen"
        # Ausgabezeilen mit Updates beginnen mit "v | ..." in der Tabelle
        lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip().startswith("v ") or line.strip().startswith("v|")
        ]
        if not lines:
            return "System aktuell (0 Updates)"
        return f"{len(lines)} Update(s) verfügbar"

    def upgrade(self) -> tuple[bool, str]:
        if not _which("pkexec"):
            return False, "pkexec nicht verfügbar — bitte manuell 'sudo zypper update' ausführen"
        result = _run(["pkexec", "zypper", "--non-interactive", "update"], TIMEOUT_UPGRADE)
        if result is None:
            return False, "Fehler oder Timeout beim Update"
        if result.returncode == 0:
            return True, "Update erfolgreich abgeschlossen"
        return False, (result.stderr or result.stdout or "Unbekannter Fehler").strip()[:500]


_DETECTORS: list[tuple[str, type]] = [
    ("dnf5", DnfManager),
    ("dnf", DnfManager),
    ("apt-get", AptManager),
    ("apt", AptManager),
    ("pacman", PacmanManager),
    ("zypper", ZypperManager),
]


def detect_package_manager() -> PackageManager | None:
    """Ermittelt den ersten verfügbaren, unterstützten Paketmanager."""
    seen_ids: set[str] = set()
    for binary, cls in _DETECTORS:
        if not _which(binary):
            continue
        instance = cls()
        if instance.id in seen_ids:
            continue
        seen_ids.add(instance.id)
        return instance
    return None
