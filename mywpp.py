#!/usr/bin/env python3
"""mywpp — troca de wallpaper (fila embaralhada, 2 monitores) + import de mídia DJI via MTP.

Substitui: set-wallpaper, next-wallpaper, kill-wallpaper, sync-dji.
"""

from __future__ import annotations

import fcntl
import random
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

WALLPAPER_DIR = Path.home() / "Imagens" / "wallpapers"
VIDEO_DIR = Path.home() / "Imagens" / "videos_drone"
DJI_STATE_DIR = Path.home() / ".local" / "share" / "dji-sync"
BLACKLIST = DJI_STATE_DIR / "deleted.txt"

IDX_FILE = Path.home() / ".local" / "share" / "hypr-wallpaper-idx"
ORDER_FILE = Path.home() / ".local" / "share" / "hypr-wallpaper-order"
LOCK_FILE = Path.home() / ".local" / "share" / "hypr-wallpaper.lock"

MONITORS = ["eDP-1", "HDMI-A-1"]
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
MTP_ALBUM_NAMES = [
    "Armazenamento%20interno%20compartilhado",
    "Internal%20shared%20storage",
    "Internal%20Storage",
]


# ========================= Fila de wallpapers =========================

@contextmanager
def queue_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def current_files() -> list[str]:
    if not WALLPAPER_DIR.is_dir():
        return []
    return sorted(str(p) for p in WALLPAPER_DIR.iterdir() if p.suffix.lower() in PHOTO_EXTS)


def load_queue() -> list[str]:
    """Ordem embaralhada e persistida. Só reembaralha se o conjunto de arquivos mudou."""
    files = current_files()
    if ORDER_FILE.exists():
        saved = ORDER_FILE.read_text().splitlines()
        if sorted(saved) == sorted(files):
            return saved
    images = files[:]
    random.shuffle(images)
    save_queue(images)
    return images


def save_queue(images: list[str]) -> None:
    ORDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    ORDER_FILE.write_text("\n".join(images) + ("\n" if images else ""))


def read_idx() -> int:
    if IDX_FILE.exists():
        try:
            return int(IDX_FILE.read_text().strip())
        except ValueError:
            return 0
    return 0


def write_idx(idx: int) -> None:
    IDX_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDX_FILE.write_text(str(idx))


def load_blacklist() -> set[str]:
    if not BLACKLIST.exists():
        return set()
    return {line.strip() for line in BLACKLIST.read_text().splitlines() if line.strip()}


def blacklist_add(name: str) -> None:
    BLACKLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(BLACKLIST, "a") as fh:
        fh.write(name + "\n")


# ========================= hyprctl / notify =========================

def hyprctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True)


def notify(title: str, body: str) -> None:
    subprocess.run(["notify-send", title, body], capture_output=True)


def apply_wallpapers(images: list[str], idx: int) -> None:
    """Preload + aplica os próximos len(MONITORS) wallpapers a partir de idx."""
    total = len(images)
    for offset, monitor in enumerate(MONITORS):
        img = images[(idx + offset) % total]
        hyprctl("hyprpaper", "preload", img)
    for _ in range(20):
        loaded = hyprctl("hyprpaper", "listloaded").stdout
        if images[idx % total] in loaded:
            break
        time.sleep(0.1)
    for offset, monitor in enumerate(MONITORS):
        img = images[(idx + offset) % total]
        hyprctl("hyprpaper", "wallpaper", f"{monitor},{img}")


# ========================= Subcomandos =========================

def cmd_boot(_args) -> int:
    """Roda no exec-once do Hyprland: avança a fila e (re)inicia o hyprpaper."""
    conf = Path.home() / ".config" / "hypr" / "hyprpaper.conf"
    with queue_lock():
        images = load_queue()
        if not images:
            print(f"Nenhuma imagem em {WALLPAPER_DIR}", file=sys.stderr)
            return 1
        idx = (read_idx() + 1) % len(images)
        write_idx(idx)

        lines = []
        seen = set()
        for offset, monitor in enumerate(MONITORS):
            img = images[(idx + offset) % len(images)]
            if img not in seen:
                lines.append(f"preload = {img}")
                seen.add(img)
            lines.append(f"wallpaper = {monitor},{img}")
        conf.write_text("\n".join(lines) + "\n")

    subprocess.run(["pkill", "-x", "hyprpaper"], capture_output=True)
    time.sleep(0.2)
    subprocess.Popen(["hyprpaper"], start_new_session=True)
    return 0


def cmd_next(_args) -> int:
    """Bind Super+W: avança para o próximo wallpaper, descarrega o antigo."""
    with queue_lock():
        images = load_queue()
        if not images:
            return 1
        idx = read_idx()
        old_img = images[idx % len(images)]
        idx = (idx + 1) % len(images)
        write_idx(idx)
        apply_wallpapers(images, idx)
        if old_img != images[idx % len(images)]:
            hyprctl("hyprpaper", "unload", old_img)
    return 0


def cmd_prev(_args) -> int:
    """Volta para o wallpaper anterior, descarrega o atual seguinte."""
    with queue_lock():
        images = load_queue()
        if not images:
            return 1
        idx = read_idx()
        old_img = images[idx % len(images)]
        idx = (idx - 1) % len(images)
        write_idx(idx)
        apply_wallpapers(images, idx)
        if old_img != images[idx % len(images)]:
            hyprctl("hyprpaper", "unload", old_img)
    return 0


def cmd_delete(args) -> int:
    """Bind Super+Shift+W: remove o wallpaper atual e avança.

    Por padrão marca o arquivo na blacklist (nunca mais reimportado pelo
    syncdji). Use --keep quando o arquivo local corrompeu mas o original no
    celular está ok: o arquivo some da fila local mas pode ser rebaixado.
    """
    with queue_lock():
        images = load_queue()
        if len(images) <= 1:
            notify("mywpp delete", "Só resta um wallpaper — não é possível remover.")
            return 1
        idx = read_idx()
        current = images[idx % len(images)]

        hyprctl("hyprpaper", "unload", current)
        Path(current).unlink(missing_ok=True)

        if not args.keep:
            blacklist_add(Path(current).name)

        images = [img for img in images if img != current]
        save_queue(images)
        idx = idx % len(images)
        write_idx(idx)
        apply_wallpapers(images, idx)

    notify("Wallpaper removido", Path(current).name)
    return 0


def _mtp_base() -> str | None:
    script = """
import gi; gi.require_version('Gio', '2.0')
from gi.repository import Gio
vm = Gio.VolumeMonitor.get()
for v in vm.get_volumes():
    ar = v.get_activation_root()
    if ar and ar.get_uri().startswith('mtp://'):
        print(ar.get_uri().rstrip('/'))
        break
"""
    proc = subprocess.run(["python3", "-c", script], capture_output=True, text=True)
    base = proc.stdout.strip()
    return base or None


def _mtp_album_path(mtp_base: str) -> str | None:
    mounted = subprocess.run(["gio", "mount", "-l"], capture_output=True, text=True).stdout
    if mtp_base not in mounted:
        subprocess.run(["gio", "mount", f"{mtp_base}/"], capture_output=True)
        time.sleep(1)

    for storage in MTP_ALBUM_NAMES:
        candidate = f"{mtp_base}/{storage}/DCIM/DJI%20Album"
        if subprocess.run(["gio", "list", f"{candidate}/"], capture_output=True).returncode == 0:
            return candidate
    return None


def cmd_syncdji(_args) -> int:
    """Importa fotos/vídeos novos do DJI Album do celular via MTP."""
    DJI_STATE_DIR.mkdir(parents=True, exist_ok=True)
    WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    print("Conectando ao celular...")
    mtp_base = _mtp_base()
    if not mtp_base:
        print("\nERRO: dispositivo MTP nao encontrado.\nConecte o celular e desbloqueie a tela.\n", file=sys.stderr)
        return 1

    mtp_path = _mtp_album_path(mtp_base)
    if not mtp_path:
        print("\nERRO: DJI Album nao encontrado no dispositivo.\nVerifique se o app DJI Fly criou a pasta DCIM/DJI Album.\n", file=sys.stderr)
        return 1

    print("Lendo DJI Album...\n")
    blacklisted = load_blacklist()

    listing = subprocess.run(["gio", "list", f"{mtp_path}/"], capture_output=True, text=True).stdout
    filenames = [line for line in listing.splitlines() if line.strip()]

    copied_photos = copied_videos = skipped_exists = skipped_blacklist = errors = 0

    for filename in filenames:
        ext = Path(filename).suffix.lower()
        if ext in PHOTO_EXTS:
            if filename in blacklisted:
                skipped_blacklist += 1
                continue
            dest = WALLPAPER_DIR / filename
            if dest.exists():
                skipped_exists += 1
                continue
            print(f"  [foto]  {filename} ... ", end="")
            ok = subprocess.run(["gio", "copy", f"{mtp_path}/{filename}", str(dest)]).returncode == 0
            print("ok" if ok else "ERRO")
            copied_photos += ok
            errors += not ok

        elif ext in VIDEO_EXTS:
            dest = VIDEO_DIR / filename
            if dest.exists():
                skipped_exists += 1
                continue
            print(f"  [video] {filename} ... ", end="")
            ok = subprocess.run(["gio", "copy", f"{mtp_path}/{filename}", str(dest)]).returncode == 0
            print("ok" if ok else "ERRO")
            copied_videos += ok
            errors += not ok

    if copied_videos > 0:
        print("Gerando thumbnails dos videos novos...")
        subprocess.run(["dji-thumbs", str(VIDEO_DIR)])

    print("\n----------------------------------------")
    print(f"  Fotos importadas : {copied_photos}")
    print(f"  Videos importados: {copied_videos}")
    print(f"  Ja existiam      : {skipped_exists}")
    print(f"  Ignoradas        : {skipped_blacklist}  (excluidas antes)")
    if errors:
        print(f"  Erros            : {errors}")
    print("----------------------------------------\n")

    notify("sync-dji", f"{copied_photos} foto(s) e {copied_videos} video(s) importado(s)")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="mywpp")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("boot", help="inicializa o hyprpaper com o próximo wallpaper (exec-once)")
    sub.add_parser("next", help="avança para o próximo wallpaper")
    sub.add_parser("prev", help="volta para o wallpaper anterior")

    p_delete = sub.add_parser("delete", help="remove o wallpaper atual e avança")
    p_delete.add_argument(
        "-k", "--keep", action="store_true",
        help="não bloquear reimportação (arquivo local corrompeu, mas o original no celular está ok)",
    )

    sub.add_parser("syncdji", help="importa fotos/vídeos novos do celular DJI via MTP")

    args = parser.parse_args()
    handlers = {
        "boot": cmd_boot,
        "next": cmd_next,
        "prev": cmd_prev,
        "delete": cmd_delete,
        "syncdji": cmd_syncdji,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
