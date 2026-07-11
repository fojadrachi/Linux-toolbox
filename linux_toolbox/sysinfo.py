"""
sysinfo.py — Datensammlung für Linux Toolbox.

Jede Funktion ist defensiv geschrieben: fehlende Tools, fehlende Rechte oder
Timeouts führen NIE zu einem Absturz, sondern liefern einen sprechenden
Platzhalter-String zurück (z. B. "nicht installiert", "n/a (root nötig)").

Alle Subprozess-Aufrufe laufen mit Timeout, damit die UI (die diese
Funktionen aus einem Hintergrund-Thread aufruft) nie hängen bleibt.

Die App ist bewusst distro-unabhängig gehalten: Hardware-, Dienst- und
Gaming-Erkennung basieren auf generischen Linux-Schnittstellen
(/proc, /sys, systemctl, which). Nur die Paket-Update-Prüfung unterscheidet
sich zwischen Distributionen — dafür siehe pkgmanager.py.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field

from linux_toolbox import pkgmanager

DEFAULT_TIMEOUT = 3  # Sekunden für schnelle Checks
SLOW_TIMEOUT = 20  # Sekunden für Flatpak-Update-Checks

NA = "n/a"


def _run(cmd: list[str], timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """Führt ein Kommando aus und gibt stdout zurück, oder None bei Fehler."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _read_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


# --------------------------------------------------------------------------
# Hardwareübersicht
# --------------------------------------------------------------------------


def get_cpu_info() -> str:
    data = _read_file("/proc/cpuinfo")
    if data:
        for line in data.splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    out = _run(["lscpu"])
    if out:
        for line in out.splitlines():
            if line.startswith("Model name:"):
                return line.split(":", 1)[1].strip()
    return NA


def get_gpu_info() -> str:
    out = _run(["lspci", "-nnk"])
    if out:
        gpus = []
        for line in out.splitlines():
            low = line.lower()
            if "vga compatible controller" in low or "3d controller" in low:
                # Beispiel: "01:00.0 VGA compatible controller [0300]: NVIDIA Corporation TU106 [GeForce RTX 2060] [10de:1f08] (rev a1)"
                try:
                    name = line.split(":", 2)[2].strip()
                except IndexError:
                    name = line.strip()
                # Klammer-Suffix mit PCI-IDs abschneiden, wenn vorhanden
                if "[" in name:
                    parts = name.split("[")
                    name = parts[0].strip()
                    # bei NVIDIA steckt der Modellname oft in eckigen Klammern
                    for part in parts[1:]:
                        if "GeForce" in part or "Radeon" in part or "RTX" in part or "GTX" in part:
                            name += f" [{part.split(']')[0]}]"
                            break
                gpus.append(name)
        if gpus:
            return ", ".join(gpus)
    return NA


def get_ram_info() -> str:
    data = _read_file("/proc/meminfo")
    if data:
        for line in data.splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                gb = kb / 1024 / 1024
                return f"{gb:.1f} GB"
    return NA


def get_mainboard_info() -> str:
    vendor = _read_file("/sys/class/dmi/id/board_vendor")
    name = _read_file("/sys/class/dmi/id/board_name")
    if vendor or name:
        combined = " ".join(p for p in (vendor, name) if p)
        return combined or NA
    return f"{NA} (root nötig)"


def get_kernel_version() -> str:
    try:
        return platform.release()
    except Exception:
        out = _run(["uname", "-r"])
        return out or NA


def get_distro_info() -> str:
    data = _read_file("/etc/os-release")
    if data:
        for line in data.splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    out = _run(["uname", "-sr"])
    return out or NA


def get_desktop_env() -> str:
    de = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION")
    return de or NA


# --------------------------------------------------------------------------
# NVIDIA-Erkennung
# --------------------------------------------------------------------------


def get_nvidia_driver_version() -> str:
    out = _run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
    if out:
        return out.splitlines()[0].strip()
    version = _read_file("/sys/module/nvidia/version")
    if version:
        return version
    return "kein NVIDIA-Treiber erkannt"


def get_session_type() -> str:
    session = os.environ.get("XDG_SESSION_TYPE")
    if session:
        return session
    out = _run(["loginctl", "show-session", "self", "-p", "Type"])
    if out and "=" in out:
        return out.split("=", 1)[1].strip()
    return NA


def get_vulkan_info() -> str:
    if not _which("vulkaninfo"):
        return "vulkaninfo nicht installiert"
    out = _run(["vulkaninfo", "--summary"], timeout=5)
    if out:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("apiVersion"):
                return line.split("=", 1)[-1].strip()
        # Fallback: irgendeine Versionszeile
        for line in out.splitlines():
            if "version" in line.lower():
                return line.strip()
    return NA


def get_opengl_info() -> str:
    if _which("glxinfo"):
        out = _run(["glxinfo", "-B"], timeout=5)
        if out:
            for line in out.splitlines():
                if "OpenGL version string" in line:
                    return line.split(":", 1)[1].strip()
        return NA
    return "glxinfo nicht installiert (mesa-demos / glx-utils / mesa-utils)"


# --------------------------------------------------------------------------
# Speicher
# --------------------------------------------------------------------------


REAL_FS_TYPES = {
    "ext2", "ext3", "ext4", "btrfs", "xfs", "vfat", "ntfs", "ntfs3",
    "exfat", "f2fs", "zfs", "reiserfs",
}


@dataclass
class DiskUsageEntry:
    mountpoint: str
    fstype: str
    total_gb: float
    used_gb: float
    percent: float


def get_storage_info() -> list[DiskUsageEntry]:
    entries: list[DiskUsageEntry] = []
    mounts = _read_file("/proc/mounts")
    if not mounts:
        return entries
    seen_devices: set[str] = set()
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mountpoint, fstype = parts[0], parts[1], parts[2]
        if fstype not in REAL_FS_TYPES:
            continue
        if device in seen_devices:
            continue
        try:
            usage = shutil.disk_usage(mountpoint)
        except OSError:
            continue
        if usage.total == 0:
            continue
        seen_devices.add(device)
        entries.append(
            DiskUsageEntry(
                mountpoint=mountpoint,
                fstype=fstype,
                total_gb=usage.total / (1024**3),
                used_gb=usage.used / (1024**3),
                percent=(usage.used / usage.total) * 100 if usage.total else 0.0,
            )
        )
    entries.sort(key=lambda e: e.mountpoint)
    return entries


def get_smart_status() -> str:
    if not _which("smartctl"):
        return "smartctl nicht installiert (smartmontools)"
    if os.geteuid() != 0:
        return "n/a (smartctl benötigt root/sudo)"
    devices = []
    try:
        for entry in os.listdir("/dev"):
            if entry.startswith(("sd", "nvme")) and (
                entry[-1].isdigit() is False or entry.startswith("nvme")
            ):
                # grobe Filterung: sda, sdb, nvme0n1 ... keine Partitionen
                if entry.startswith("nvme") and "p" in entry.split("n", 1)[-1]:
                    continue
                if entry.startswith("sd") and entry[-1].isdigit():
                    continue
                devices.append(f"/dev/{entry}")
    except OSError:
        pass
    if not devices:
        return NA
    results = []
    for dev in devices:
        out = _run(["smartctl", "-H", dev], timeout=5)
        if out:
            for line in out.splitlines():
                if "overall-health" in line.lower() or "smart health status" in line.lower():
                    status = line.split(":", 1)[-1].strip()
                    results.append(f"{dev}: {status}")
                    break
    return "; ".join(results) if results else NA


# --------------------------------------------------------------------------
# Updates (langsam – im Hintergrund-Thread aufrufen!)
# --------------------------------------------------------------------------
#
# Die eigentliche Paketmanager-Logik (dnf/apt/pacman/zypper) steckt in
# pkgmanager.py. Hier wird nur der erkannte Manager verwendet — ist keiner
# vorhanden, wird das transparent angezeigt statt abzustürzen.

_PKG_MANAGER = pkgmanager.detect_package_manager()


def get_package_manager_name() -> str:
    return _PKG_MANAGER.display_name if _PKG_MANAGER else "kein unterstützter Paketmanager gefunden"


def get_package_updates() -> str:
    if _PKG_MANAGER is None:
        return "kein unterstützter Paketmanager gefunden (dnf/apt/pacman/zypper)"
    return _PKG_MANAGER.check_updates()


def run_package_upgrade() -> tuple[bool, str]:
    if _PKG_MANAGER is None:
        return False, "kein unterstützter Paketmanager gefunden"
    return _PKG_MANAGER.upgrade()


def get_flatpak_updates() -> str:
    if not _which("flatpak"):
        return "Flatpak nicht installiert"
    out = _run(["flatpak", "remote-ls", "--updates"], timeout=SLOW_TIMEOUT)
    if out is None:
        return "Fehler beim Prüfen"
    if not out.strip():
        return "0 Flatpak-Updates"
    count = len([l for l in out.splitlines() if l.strip()])
    return f"{count} Flatpak-Update(s) verfügbar"


def run_flatpak_update() -> tuple[bool, str]:
    if not _which("flatpak"):
        return False, "Flatpak nicht installiert"
    try:
        result = subprocess.run(
            ["flatpak", "update", "-y"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"Fehler: {exc}"
    if result.returncode == 0:
        return True, "Flatpaks aktualisiert"
    return False, (result.stderr or result.stdout or "Unbekannter Fehler").strip()[:500]


# --------------------------------------------------------------------------
# Dienste
# --------------------------------------------------------------------------


def _systemctl_is_active(units: str | list[str], user: bool = False) -> str:
    if not _which("systemctl"):
        return NA
    unit_list = [units] if isinstance(units, str) else units
    for unit in unit_list:
        cmd = ["systemctl"]
        if user:
            cmd.append("--user")
        cmd += ["is-active", unit]
        out = _run(cmd, timeout=3)
        if out is None:
            continue
        out = out.strip()
        if out == "active":
            return "läuft"
        if out in ("inactive", "failed", "unknown"):
            exists_cmd = ["systemctl"]
            if user:
                exists_cmd.append("--user")
            exists_cmd += ["list-unit-files", unit]
            exists = _run(exists_cmd, timeout=3)
            if exists and unit in exists:
                return "installiert, gestoppt" if out != "failed" else "fehlgeschlagen"
            # diese Unit existiert nicht — ggf. nächsten Namen probieren
            continue
        return out
    return "nicht installiert"


def get_docker_status() -> str:
    if _which("docker"):
        return _systemctl_is_active("docker.service")
    return "nicht installiert"


def get_podman_status() -> str:
    if _which("podman"):
        status = _systemctl_is_active("podman.socket")
        if status == "nicht installiert":
            return "installiert (kein Socket aktiv)"
        return status
    return "nicht installiert"


def get_steam_status() -> str:
    if _which("steam"):
        return "installiert (nativ)"
    flatpak_out = _run(["flatpak", "list", "--app", "--columns=application"], timeout=5)
    if flatpak_out and "com.valvesoftware.Steam" in flatpak_out:
        return "installiert (Flatpak)"
    return "nicht installiert"


def get_ssh_status() -> str:
    # Der Binary-Name ist meist "sshd", der systemd-Unit-Name unterscheidet
    # sich aber je nach Distro: "sshd.service" (Fedora/Arch/openSUSE) vs.
    # "ssh.service" (Debian/Ubuntu).
    if _which("sshd") or os.path.exists("/usr/sbin/sshd"):
        return _systemctl_is_active(["sshd.service", "ssh.service"])
    return "nicht installiert"


def get_tailscale_status() -> str:
    if not _which("tailscale"):
        return "nicht installiert"
    status = _systemctl_is_active("tailscaled.service")
    out = _run(["tailscale", "status"], timeout=3)
    if out and "Logged out" not in out and out.strip():
        first_line = out.splitlines()[0] if out.splitlines() else ""
        if first_line and not first_line.lower().startswith("tailscale is stopped"):
            return f"{status} · verbunden"
    return status


# --------------------------------------------------------------------------
# Gaming
# --------------------------------------------------------------------------


def get_mangohud_status() -> str:
    if _which("mangohud"):
        return "installiert"
    # Flatpak-Variante prüfen
    out = _run(["flatpak", "list", "--columns=application"], timeout=5)
    if out and "org.freedesktop.Platform.VulkanLayer.MangoHud" in out:
        return "installiert (Flatpak-Layer)"
    return "nicht installiert"


def get_gamescope_status() -> str:
    return "installiert" if _which("gamescope") else "nicht installiert"


def get_gamemode_status() -> str:
    if not _which("gamemoded"):
        return "nicht installiert"
    out = _run(["gamemoded", "-s"], timeout=3)
    if out:
        if "is active" in out.lower() or "running" in out.lower():
            return "installiert, aktiv"
        return "installiert, inaktiv"
    return "installiert"


def get_proton_ge_status() -> str:
    candidate_dirs = [
        os.path.expanduser("~/.steam/root/compatibilitytools.d"),
        os.path.expanduser("~/.local/share/Steam/compatibilitytools.d"),
        os.path.expanduser(
            "~/.var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d"
        ),
    ]
    found = []
    for d in candidate_dirs:
        if os.path.isdir(d):
            try:
                for entry in os.listdir(d):
                    if "proton" in entry.lower() or "ge-" in entry.lower():
                        found.append(entry)
            except OSError:
                continue
    if found:
        return ", ".join(sorted(set(found)))
    return "nicht gefunden"


def get_wine_version() -> str:
    if not _which("wine"):
        return "nicht installiert"
    out = _run(["wine", "--version"], timeout=5)
    return out or NA


# --------------------------------------------------------------------------
# Kompletter Sammel-Snapshot für den Support-Bericht
# --------------------------------------------------------------------------


@dataclass
class Snapshot:
    distro: str = NA
    kernel: str = NA
    cpu: str = NA
    gpu: str = NA
    ram: str = NA
    mainboard: str = NA
    desktop: str = NA
    nvidia_driver: str = NA
    session_type: str = NA
    vulkan: str = NA
    opengl: str = NA
    storage: list[DiskUsageEntry] = field(default_factory=list)
    smart: str = NA
    pkg_manager: str = NA
    pkg_updates: str = NA
    flatpak_updates: str = NA
    docker: str = NA
    podman: str = NA
    steam: str = NA
    ssh: str = NA
    tailscale: str = NA
    mangohud: str = NA
    gamescope: str = NA
    gamemode: str = NA
    proton_ge: str = NA
    wine: str = NA


def collect_fast_snapshot() -> Snapshot:
    """Alles, was schnell geht (keine Netzwerk-/Paketmanager-Abfragen)."""
    snap = Snapshot()
    snap.distro = get_distro_info()
    snap.kernel = get_kernel_version()
    snap.cpu = get_cpu_info()
    snap.gpu = get_gpu_info()
    snap.ram = get_ram_info()
    snap.mainboard = get_mainboard_info()
    snap.desktop = get_desktop_env()
    snap.nvidia_driver = get_nvidia_driver_version()
    snap.session_type = get_session_type()
    snap.vulkan = get_vulkan_info()
    snap.opengl = get_opengl_info()
    snap.storage = get_storage_info()
    snap.smart = get_smart_status()
    snap.pkg_manager = get_package_manager_name()
    snap.docker = get_docker_status()
    snap.podman = get_podman_status()
    snap.steam = get_steam_status()
    snap.ssh = get_ssh_status()
    snap.tailscale = get_tailscale_status()
    snap.mangohud = get_mangohud_status()
    snap.gamescope = get_gamescope_status()
    snap.gamemode = get_gamemode_status()
    snap.proton_ge = get_proton_ge_status()
    snap.wine = get_wine_version()
    return snap


def collect_updates(snap: Snapshot) -> None:
    """Langsame Update-Checks (Paketmanager/Flatpak) — separat aufrufen, im Thread."""
    snap.pkg_updates = get_package_updates()
    snap.flatpak_updates = get_flatpak_updates()


def format_report(snap: Snapshot) -> str:
    """Erzeugt den Ein-Klick-Kopieren Support-Bericht im kompakten Format."""
    lines = [
        snap.distro,
        f"Kernel: {snap.kernel}",
        f"CPU: {snap.cpu}",
        f"GPU: {snap.gpu}",
        f"Treiber: {snap.nvidia_driver}",
        f"Session: {snap.session_type}",
        f"RAM: {snap.ram}",
        f"Paketmanager: {snap.pkg_manager}",
        f"Updates: {snap.pkg_updates}",
        f"Flatpaks: {snap.flatpak_updates}",
        f"Steam: {snap.steam}",
    ]
    return "\n".join(lines)
