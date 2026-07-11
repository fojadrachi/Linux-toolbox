"""
main.py — GTK4 / libadwaita Oberfläche für Linux Toolbox.

Startet eine Adw.Application mit einem Fenster, das die Systeminfos in
mehreren Adw.PreferencesGroup-Abschnitten anzeigt. Langsame Abfragen
(Paketmanager-/Flatpak-Updates, SMART) laufen in Hintergrund-Threads,
damit die UI nie einfriert.
"""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gio, Gtk  # noqa: E402

from linux_toolbox import sysinfo  # noqa: E402

APP_ID = "de.fojadrachi.LinuxToolbox"
APP_VERSION = "1.0.0"


def _row(title: str, value: str, subtitle: str | None = None) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    value_label = Gtk.Label(label=value)
    value_label.add_css_class("dim-label")
    value_label.set_selectable(True)
    value_label.set_wrap(True)
    value_label.set_xalign(1.0)
    row.add_suffix(value_label)
    row.value_label = value_label  # type: ignore[attr-defined]
    return row


def _update_row(row: Adw.ActionRow, value: str) -> None:
    row.value_label.set_label(value)  # type: ignore[attr-defined]


class LinuxToolboxWindow(Adw.ApplicationWindow):
    def __init__(self, app: "LinuxToolboxApp") -> None:
        super().__init__(application=app, title="Linux Toolbox")
        self.set_default_size(560, 720)

        self.snapshot = sysinfo.Snapshot()
        self._rows: dict[str, Adw.ActionRow] = {}

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_button.set_tooltip_text("Alles neu laden")
        self.refresh_button.connect("clicked", self.on_refresh_clicked)
        header.pack_start(self.refresh_button)

        self.copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.copy_button.set_tooltip_text("Support-Bericht kopieren")
        self.copy_button.add_css_class("suggested-action")
        self.copy_button.connect("clicked", self.on_copy_clicked)
        header.pack_end(self.copy_button)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Über Linux Toolbox", "app.about")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        toolbar_view.set_content(scroller)

        page = Adw.PreferencesPage()
        scroller.set_child(page)

        self._build_hardware_group(page)
        self._build_nvidia_group(page)
        self._build_storage_group(page)
        self._build_updates_group(page)
        self._build_services_group(page)
        self._build_gaming_group(page)

        self.storage_group: Adw.PreferencesGroup | None = None
        self._storage_page_ref = page

        # Erste Befüllung
        self.load_fast_data()
        self.refresh_updates_async()

    # -- UI-Aufbau -----------------------------------------------------

    def _add_group(self, page: Adw.PreferencesPage, title: str) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title)
        page.add(group)
        return group

    def _add_row(self, group: Adw.PreferencesGroup, key: str, title: str) -> None:
        row = _row(title, "…")
        group.add(row)
        self._rows[key] = row

    def _build_hardware_group(self, page: Adw.PreferencesPage) -> None:
        group = self._add_group(page, "Hardwareübersicht")
        for key, title in [
            ("distro", "Distribution"),
            ("cpu", "CPU"),
            ("gpu", "GPU"),
            ("ram", "RAM"),
            ("mainboard", "Mainboard"),
            ("kernel", "Kernel"),
            ("desktop", "Desktop"),
        ]:
            self._add_row(group, key, title)

    def _build_nvidia_group(self, page: Adw.PreferencesPage) -> None:
        group = self._add_group(page, "NVIDIA-Erkennung")
        for key, title in [
            ("nvidia_driver", "Treiberversion"),
            ("session_type", "Wayland/X11"),
            ("vulkan", "Vulkan"),
            ("opengl", "OpenGL"),
        ]:
            self._add_row(group, key, title)

    def _build_storage_group(self, page: Adw.PreferencesPage) -> None:
        self.storage_group = self._add_group(page, "Speicher")
        self._add_row(self.storage_group, "smart", "SMART-Status")

    def _build_updates_group(self, page: Adw.PreferencesPage) -> None:
        group = self._add_group(page, "Updates")
        self._add_row(group, "pkg_manager", "Erkannter Paketmanager")
        self._add_row(group, "pkg_updates", "Verfügbare Paket-Updates")
        self._add_row(group, "flatpak_updates", "Flatpak-Updates")

        button_row = Adw.ActionRow(title="Ein Klick zum Aktualisieren")
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pkg_upgrade_btn = Gtk.Button(label="Pakete aktualisieren")
        self.pkg_upgrade_btn.connect("clicked", self.on_package_upgrade_clicked)
        flatpak_btn = Gtk.Button(label="Flatpaks aktualisieren")
        flatpak_btn.connect("clicked", self.on_flatpak_upgrade_clicked)
        button_box.append(self.pkg_upgrade_btn)
        button_box.append(flatpak_btn)
        button_row.add_suffix(button_box)
        group.add(button_row)

    def _build_services_group(self, page: Adw.PreferencesPage) -> None:
        group = self._add_group(page, "Dienste")
        for key, title in [
            ("docker", "Docker"),
            ("podman", "Podman"),
            ("steam", "Steam"),
            ("ssh", "SSH"),
            ("tailscale", "Tailscale"),
        ]:
            self._add_row(group, key, title)

    def _build_gaming_group(self, page: Adw.PreferencesPage) -> None:
        group = self._add_group(page, "Gaming")
        for key, title in [
            ("mangohud", "MangoHud installiert?"),
            ("gamescope", "Gamescope?"),
            ("gamemode", "Gamemode?"),
            ("proton_ge", "Proton-GE?"),
            ("wine", "Wine-Version"),
        ]:
            self._add_row(group, key, title)

    # -- Datenanzeige ----------------------------------------------------

    def _apply_fast_snapshot_to_ui(self) -> None:
        snap = self.snapshot
        mapping = {
            "distro": snap.distro,
            "cpu": snap.cpu,
            "gpu": snap.gpu,
            "ram": snap.ram,
            "mainboard": snap.mainboard,
            "kernel": snap.kernel,
            "desktop": snap.desktop,
            "nvidia_driver": snap.nvidia_driver,
            "session_type": snap.session_type,
            "vulkan": snap.vulkan,
            "opengl": snap.opengl,
            "smart": snap.smart,
            "pkg_manager": snap.pkg_manager,
            "docker": snap.docker,
            "podman": snap.podman,
            "steam": snap.steam,
            "ssh": snap.ssh,
            "tailscale": snap.tailscale,
            "mangohud": snap.mangohud,
            "gamescope": snap.gamescope,
            "gamemode": snap.gamemode,
            "proton_ge": snap.proton_ge,
            "wine": snap.wine,
        }
        for key, value in mapping.items():
            row = self._rows.get(key)
            if row is not None:
                _update_row(row, value)

        # Wenn kein Paketmanager erkannt wurde, gibt es nichts zu aktualisieren.
        self.pkg_upgrade_btn.set_sensitive(
            "kein unterstützter Paketmanager" not in snap.pkg_manager
        )

        self._rebuild_storage_rows()

    def _rebuild_storage_rows(self) -> None:
        if self.storage_group is None:
            return
        # Alte Laufwerks-Zeilen entfernen (alles außer der SMART-Zeile)
        for row in list(getattr(self, "_disk_rows", [])):
            self.storage_group.remove(row)
        self._disk_rows = []

        for entry in self.snapshot.storage:
            title = f"{entry.mountpoint} ({entry.fstype})"
            value = (
                f"{entry.used_gb:.1f} / {entry.total_gb:.1f} GB "
                f"({entry.percent:.0f}%)"
            )
            row = _row(title, value)
            self.storage_group.add(row)
            self._disk_rows.append(row)

    def _apply_update_snapshot_to_ui(self) -> None:
        _update_row(self._rows["pkg_updates"], self.snapshot.pkg_updates)
        _update_row(self._rows["flatpak_updates"], self.snapshot.flatpak_updates)

    # -- Aktionen ----------------------------------------------------

    def load_fast_data(self) -> None:
        self.spinner.start()

        def work() -> None:
            snap = sysinfo.collect_fast_snapshot()
            GLib.idle_add(self._on_fast_data_ready, snap)

        threading.Thread(target=work, daemon=True).start()

    def _on_fast_data_ready(self, snap: sysinfo.Snapshot) -> bool:
        # Update-Felder aus vorherigem Snapshot übernehmen, damit sie nicht
        # beim Neuladen der schnellen Daten überschrieben werden.
        snap.pkg_updates = self.snapshot.pkg_updates
        snap.flatpak_updates = self.snapshot.flatpak_updates
        self.snapshot = snap
        self._apply_fast_snapshot_to_ui()
        self.spinner.stop()
        return GLib.SOURCE_REMOVE

    def refresh_updates_async(self) -> None:
        def work() -> None:
            sysinfo.collect_updates(self.snapshot)
            GLib.idle_add(self._apply_update_snapshot_to_ui)

        threading.Thread(target=work, daemon=True).start()

    def on_refresh_clicked(self, _button: Gtk.Button) -> None:
        self.load_fast_data()
        self.refresh_updates_async()

    def on_copy_clicked(self, _button: Gtk.Button) -> None:
        report = sysinfo.format_report(self.snapshot)
        clipboard = self.get_clipboard()
        clipboard.set(report)
        self.toast_overlay.add_toast(Adw.Toast(title="Support-Bericht kopiert"))

    def _run_and_toast(self, func, label: str) -> None:
        self.spinner.start()

        def work() -> None:
            ok, message = func()
            GLib.idle_add(self._on_upgrade_done, ok, message, label)

        threading.Thread(target=work, daemon=True).start()

    def _on_upgrade_done(self, ok: bool, message: str, label: str) -> bool:
        self.spinner.stop()
        title = f"{label}: {message}" if ok else f"{label} fehlgeschlagen: {message}"
        self.toast_overlay.add_toast(Adw.Toast(title=title[:120]))
        if ok:
            self.on_refresh_clicked(self.refresh_button)
        return GLib.SOURCE_REMOVE

    def on_package_upgrade_clicked(self, _button: Gtk.Button) -> None:
        label = self.snapshot.pkg_manager if self.snapshot.pkg_manager != sysinfo.NA else "Paket"
        self._run_and_toast(sysinfo.run_package_upgrade, f"{label}-Update")

    def on_flatpak_upgrade_clicked(self, _button: Gtk.Button) -> None:
        self._run_and_toast(sysinfo.run_flatpak_update, "Flatpak-Update")


class LinuxToolboxApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: LinuxToolboxWindow | None = None

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about)
        self.add_action(about_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self) -> None:  # noqa: N802 (GTK naming convention)
        if self.window is None:
            self.window = LinuxToolboxWindow(self)
        self.window.present()

    def on_about(self, *_args) -> None:
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name="Linux Toolbox",
            application_icon="utilities-system-monitor-symbolic",
            version=APP_VERSION,
            developer_name="bgol",
            comments=(
                "Eine kleine native GTK4/libadwaita-App, die alle wichtigen "
                "Systeminfos und Wartungsaufgaben an einem Ort bündelt — für "
                "Fedora, Debian/Ubuntu, Arch und openSUSE-basierte Systeme."
            ),
            license_type=Gtk.License.MIT_X11,
            website="https://fojadrachi.com",
        )
        about.present()


def main() -> int:
    app = LinuxToolboxApp()
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
