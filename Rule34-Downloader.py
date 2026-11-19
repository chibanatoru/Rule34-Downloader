#!/usr/bin/env python3
"""chibanatoru Downloader - Rule34 + Danbooru (based on chibanatoru/Rule34-Downloader).

Python packages (requests, tqdm, colorama, pillow) are installed automatically on first run.
Optional: ffmpeg in PATH (converts webm/gif to mp4)   e.g.  winget install ffmpeg

python chibanatoru-Downloader.py

- Original files (file_url) are downloaded - no resized/sample versions.
- Images are saved as 1.png, 2.png, 3.png ... (lossless PNG, same pixels as the
  original); videos as mp4 in the same numbering (1.png, 2.mp4, 3.png ...).
  webm -> mp4 is a remux (no re-encode) when possible, otherwise visually lossless.
- Any other file type (zip/ugoira, swf, ...) is still downloaded and kept as is,
  with the same numbering (4.zip).
- Numbers follow the order of the results.
- Each site and tag search gets its own folder:  <save folder>/<site>/<tags>/
- Re-running a search continues the numbering after the highest number in that folder.
- Credentials and the chosen save folder are stored in config.json next to the script.
"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse



# ---------------------------------------------------------------------------
# Python packages are installed automatically on first run if they are missing.
# (ffmpeg is not a Python package - install it separately, e.g. winget install ffmpeg)
# ---------------------------------------------------------------------------
REQUIRED_PACKAGES = {"requests": "requests", "tqdm": "tqdm", "colorama": "colorama"}
OPTIONAL_PACKAGES = {"PIL": "pillow"}      # without it images are kept in their original format


def _missing(packages):
    found = []
    for module, pkg in packages.items():
        try:
            importlib.import_module(module)
        except ImportError:
            found.append(pkg)
    return found


def _pip_install(pkgs):
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    for extra in ([], ["--user"]):            # second try covers non-admin installs
        try:
            subprocess.check_call(base + extra + pkgs)
            importlib.invalidate_caches()
            return True
        except (subprocess.CalledProcessError, OSError):
            continue
    return False


def ensure_packages():
    need = _missing(REQUIRED_PACKAGES)
    want = _missing(OPTIONAL_PACKAGES)
    if not need and not want:
        return
    print(f"Installing missing Python packages: {', '.join(need + want)} ...")
    if need and not _pip_install(need):
        sys.exit("Could not install automatically. Run this yourself:\n  pip install " + " ".join(need + want))
    if want and not _pip_install(want):
        print("Optional package could not be installed (" + ", ".join(want) +
              "). Continuing without it - images will keep their original format.")


ensure_packages()

import requests  # noqa: E402
from colorama import Fore, Style, init as colorama_init  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
from tqdm import tqdm  # noqa: E402
from urllib3.util.retry import Retry  # noqa: E402

try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
except ImportError:
    Image = None

colorama_init()

CONFIG_FILE = Path(__file__).with_name("config.json")
DEFAULT_OUTPUT = Path.home() / "Downloads" / "Art Downloaded"
UA = "Mozilla/5.0 (compatible; chibanatoruDownloader/4.0)"
MAX_POSTS = 5000
FFMPEG = shutil.which("ffmpeg")

IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".gif"}
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".flv", ".wmv", ".mpg", ".mpeg"}
# Animated gif/webp are converted to mp4 (visually lossless re-encode).
# Set to False to keep animated gif/webp exactly as downloaded.
ANIMATED_TO_MP4 = True

DEFAULT_CONFIG = {
    "output": str(DEFAULT_OUTPUT),
    "rule34": {"user_id": "", "api_key": ""},
    "danbooru": {"login": "", "api_key": ""},
}


# ============================ config ============================
def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["output"] = saved.get("output") or cfg["output"]
            for site in ("rule34", "danbooru"):
                cfg[site].update(saved.get(site, {}))
        except Exception as e:
            print(f"{Fore.YELLOW}Could not read config.json: {e}{Style.RESET_ALL}")
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


# ============================ sites ============================
class Rule34:
    key = "rule34"
    label = "Rule34"
    per_page = 1000
    api_url = "https://api.rule34.xxx/index.php"
    fields = [("user_id", "User ID"), ("api_key", "API Key")]
    help = "Get them at: https://rule34.xxx/index.php?page=account&s=options (account required)"
    tag_note = ""

    @staticmethod
    def is_configured(c):
        return bool(c["api_key"] and c["user_id"])

    @classmethod
    def fetch_page(cls, session, c, tags, page_idx, last_id):
        params = {"page": "dapi", "s": "post", "q": "index", "json": 1,
                  "tags": " ".join(tags), "limit": cls.per_page, "pid": page_idx}
        if c["api_key"]:
            params.update(api_key=c["api_key"], user_id=c["user_id"])
        r = session.get(cls.api_url, params=params, timeout=30)
        r.raise_for_status()
        if not r.text.strip():
            return []                      # empty body = no results
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"API said: {r.text[:200]}")
        return [{"id": int(p["id"]), "url": p.get("file_url")}
                for p in data if isinstance(p, dict)]

    @classmethod
    def test(cls, session, c):
        try:
            cls.fetch_page(session, c, ["rating:safe"], 0, None)
            return True, "API key accepted."
        except Exception as e:
            return False, str(e)


class Danbooru:
    key = "danbooru"
    label = "Danbooru"
    per_page = 200
    api_url = "https://danbooru.donmai.us"
    fields = [("login", "Username (login, NOT the numeric ID)"), ("api_key", "API Key")]
    help = ("Create a key at: https://danbooru.donmai.us/profile  ->  API Keys\n"
            "  Works without a key too (anonymous), but free accounts are limited to 2 tags per search.")
    tag_note = "Accounts without Gold are limited to 2 tags per search."

    @staticmethod
    def is_configured(c):
        return bool(c["api_key"] and c["login"])

    @staticmethod
    def _auth(c):
        return {"login": c["login"], "api_key": c["api_key"]} if c["api_key"] and c["login"] else {}

    @classmethod
    def fetch_page(cls, session, c, tags, page_idx, last_id):
        params = {"tags": " ".join(tags), "limit": cls.per_page,
                  "page": f"b{last_id}" if last_id else 1}     # b<id> = posts older than <id>
        params.update(cls._auth(c))
        r = session.get(f"{cls.api_url}/posts.json", params=params, timeout=30)
        if r.status_code == 422:
            raise RuntimeError("Too many tags for this account (free limit is 2).")
        r.raise_for_status()
        return [{"id": int(p["id"]), "url": p.get("file_url")}
                for p in r.json() if isinstance(p, dict)]

    @classmethod
    def test(cls, session, c):
        if not c["api_key"]:
            return False, "No API key set."
        try:
            r = session.get(f"{cls.api_url}/profile.json", params=cls._auth(c), timeout=30)
            if r.status_code in (401, 403):
                return False, "Login or API key rejected (login must be the username)."
            r.raise_for_status()
            d = r.json()
            return True, f"Logged in as {d.get('name', '?')} (level: {d.get('level_string', '?')})."
        except Exception as e:
            return False, str(e)


SITES = [Rule34, Danbooru]


# ============================ helpers ============================
def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


class Stats:
    """Live totals: files done, bytes downloaded, current speed."""

    def __init__(self):
        self.bytes = 0
        self.files = 0
        self.t0 = time.time()
        self.win_t, self.win_b, self.speed = self.t0, 0, 0.0
        self.last_draw = 0.0

    def add(self, n):
        self.bytes += n
        now = time.time()
        if now - self.win_t >= 0.5:
            self.speed = (self.bytes - self.win_b) / (now - self.win_t)
            self.win_t, self.win_b = now, self.bytes

    def text(self):
        return f"size {human(self.bytes)} | speed {human(self.speed)}/s"


def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504, 429])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def collect_posts(site, session, creds, tags, limit):
    posts, seen, last_id, page_idx = [], set(), None, 0
    while len(posts) < limit:
        batch = site.fetch_page(session, creds, tags, page_idx, last_id)
        if not batch:
            break
        last_id = min(p["id"] for p in batch)
        page_idx += 1
        for p in batch:
            if p["url"] and p["id"] not in seen:
                seen.add(p["id"])
                posts.append(p)
        print(f"  fetched {len(posts)} posts...", end="\r")
        if len(batch) < site.per_page:
            break
    print()
    return posts[:limit]


# ============================ downloading ============================
def download_file(session, url, path, label, on_bytes):
    """Resume-capable download into <path>.part, renamed to <path> on success."""
    part = str(path) + ".part"
    for attempt in range(5):
        try:
            pos = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"Range": f"bytes={pos}-"} if pos else {}
            with session.get(url, headers=headers, stream=True, timeout=120) as r:
                if r.status_code == 416:          # .part is already complete
                    os.replace(part, path)
                    return
                r.raise_for_status()
                if r.status_code != 206:
                    pos = 0                       # server ignored Range -> restart
                total = int(r.headers.get("content-length", 0)) + pos
                with open(part, "ab" if pos else "wb") as f, tqdm(
                        total=total or None, initial=pos, unit="B", unit_scale=True,
                        unit_divisor=1024, desc=label, position=1, leave=False) as bar:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))
                            on_bytes(len(chunk))
            if total and os.path.getsize(part) < total:
                raise IOError("Incomplete download")
            os.replace(part, path)
            return
        except Exception as e:
            if attempt == 4:
                raise
            tqdm.write(f"{Fore.YELLOW}  attempt {attempt + 1} failed: {e}. Retrying in {2 ** attempt}s...{Style.RESET_ALL}")
            time.sleep(2 ** attempt)


_warned = set()


def warn_once(key, msg):
    if key not in _warned:
        _warned.add(key)
        tqdm.write(f"{Fore.YELLOW}{msg}{Style.RESET_ALL}")


def to_png(src, dst):
    """Re-save the decoded pixels as PNG (lossless; keeps the ICC colour profile)."""
    with Image.open(src) as im:
        icc = im.info.get("icc_profile")
        if im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "I;16"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        kwargs = {"icc_profile": icc} if icc else {}
        im.save(dst, "PNG", **kwargs)


def run_ffmpeg(args, dst):
    r = subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args, str(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not Path(dst).exists() or Path(dst).stat().st_size == 0:
        Path(dst).unlink(missing_ok=True)
        return False
    return True


def to_mp4(src, dst):
    """Best quality first: 1) remux (no re-encode), 2) remux video + AAC audio,
    3) visually lossless x264 re-encode. Returns a note describing what happened."""
    src = str(src)
    base = ["-i", src, "-map", "0:v:0", "-map", "0:a?", "-movflags", "+faststart"]
    if run_ffmpeg(base + ["-c", "copy"], dst):
        return "remuxed to mp4, no re-encode, original quality"
    if run_ffmpeg(base + ["-c:v", "copy", "-c:a", "aac", "-b:a", "320k"], dst):
        return "remuxed to mp4, video untouched"
    if run_ffmpeg(base + ["-c:v", "libx264", "-crf", "10", "-preset", "slow", "-pix_fmt", "yuv420p",
                          "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                          "-c:a", "aac", "-b:a", "320k"], dst):
        return "re-encoded to mp4 (visually lossless, crf 10)"
    raise RuntimeError("ffmpeg could not convert this file")


def keep_original(tmp, ext, n, folder, why):
    dst = folder / f"{n}{ext}"
    os.replace(tmp, dst)
    return dst, f"kept original {ext} ({why})"


def finalize(tmp, ext, n, folder):
    """Name the file by its number. Images -> .png, videos -> .mp4, anything else
    is kept exactly as downloaded. If a conversion fails the original is kept.
    Returns (final_path, note)."""
    tmp = Path(tmp)
    kind = "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else "other"

    if kind == "other":
        return keep_original(tmp, ext, n, folder, "not an image/video format")

    if kind == "image":
        if Image is None:
            warn_once("pillow", "Pillow not installed: images are kept in their original format (pip install pillow).")
            return keep_original(tmp, ext, n, folder, "Pillow missing")
        try:
            with Image.open(tmp) as im:
                animated = getattr(im, "is_animated", False)
        except Exception as e:
            return keep_original(tmp, ext, n, folder, f"cannot read image: {e}")
        if animated:
            if not ANIMATED_TO_MP4:
                return keep_original(tmp, ext, n, folder, "animated, kept as is")
            kind = "video"
        else:
            dst = folder / f"{n}.png"
            if ext == ".png":
                os.replace(tmp, dst)
                return dst, "png, untouched"
            try:
                to_png(tmp, dst)
                tmp.unlink()
                return dst, "converted to png (lossless)"
            except Exception as e:
                Path(dst).unlink(missing_ok=True)
                return keep_original(tmp, ext, n, folder, f"png conversion failed: {e}")

    # kind == "video"
    if ext == ".mp4":
        dst = folder / f"{n}.mp4"
        os.replace(tmp, dst)
        return dst, "mp4, untouched"
    if not FFMPEG:
        warn_once("ffmpeg", "ffmpeg not found: non-mp4 videos are kept in their original format.")
        return keep_original(tmp, ext, n, folder, "ffmpeg missing")
    dst = folder / f"{n}.mp4"
    try:
        note = to_mp4(tmp, dst)
        tmp.unlink()
        return dst, note
    except Exception as e:
        return keep_original(tmp, ext, n, folder, str(e))


def numbered_files(folder):
    """Existing numbered files in the folder (1.png, 2.mp4, ...) as {number: name}."""
    found = {}
    for f in folder.iterdir():
        m = re.fullmatch(r"(\d+)\.[^.]+", f.name)
        if m:
            found[int(m.group(1))] = f.name
    return found


def download_media(site, cfg, tags, limit, output, create_cbz):
    creds = cfg[site.key]
    session = make_session()
    try:
        posts = collect_posts(site, session, creds, tags, limit)
    except Exception as e:
        print(f"{Fore.RED}API Error: {e}{Style.RESET_ALL}")
        return
    if not posts:
        print("No downloadable posts found.")
        return

    folder = Path(output) / site.key / re.sub(r"[^\w.\-]+", "_", "_".join(tags))[:100]
    folder.mkdir(parents=True, exist_ok=True)
    todo = posts
    n = max(numbered_files(folder), default=0) + 1     # continue after the highest existing number

    print(f"Found {len(posts)} posts" + (f" | numbering continues from {n}" if n > 1 else ""))
    print(f"Saving to: {folder}\n")

    stats = Stats()
    failed = 0
    overall = tqdm(total=len(todo), desc="Overall", unit="file", position=0,
                   bar_format="{desc}: {n_fmt}/{total_fmt} files [{elapsed}] {postfix}")
    overall.set_postfix_str(stats.text())

    def on_bytes(n):
        stats.add(n)
        now = time.time()
        if now - stats.last_draw >= 0.25:
            stats.last_draw = now
            overall.set_postfix_str(stats.text())

    for post in todo:
        url = "https:" + post["url"] if post["url"].startswith("//") else post["url"]
        ext = os.path.splitext(urlparse(url).path)[1].lower() or ".jpg"
        tmp = folder / f"_tmp_{post['id']}{ext}"
        try:
            download_file(session, url, tmp, f"#{n}", on_bytes)
            final, note = finalize(tmp, ext, n, folder)
            n += 1
            stats.files += 1
            tqdm.write(f"{Fore.GREEN}✓ {final.name}  ({human(final.stat().st_size)}) - {note}{Style.RESET_ALL}")
        except Exception as e:
            failed += 1
            tqdm.write(f"{Fore.YELLOW}Warning: post {post['id']} failed: {e}{Style.RESET_ALL}")
        overall.update(1)
        overall.set_postfix_str(stats.text())
    overall.close()

    elapsed = max(time.time() - stats.t0, 0.001)
    print(f"\n{Fore.GREEN}Done: {stats.files} saved, {failed} failed | downloaded {human(stats.bytes)} "
          f"in {elapsed:.0f}s (avg {human(stats.bytes / elapsed)}/s){Style.RESET_ALL}")
    print(f"Folder: {folder}")

    if create_cbz:
        found = numbered_files(folder)
        names = [found[k] for k in sorted(found)
                 if os.path.splitext(found[k])[1].lower() in IMAGE_EXT]
        if names:
            cbz_path = folder / f"{folder.name}.cbz"
            try:
                with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as z:
                    for name in tqdm(names, desc="Creating CBZ", unit="file"):
                        z.write(folder / name, name)
                print(f"{Fore.GREEN}CBZ created: {cbz_path}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Failed to create CBZ: {e}{Style.RESET_ALL}")


# ============================ menus ============================
def ask(prompt, default=""):
    v = input(prompt).strip()
    return v or default


def mask(v):
    return "(not set)" if not v else (v[:4] + "*" * 6 if len(v) > 4 else "*" * len(v))


def browse_folder(initial):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=str(initial), title="Choose where to save")
        root.destroy()
        return chosen or None
    except Exception:
        print("Folder window is not available here - paste the path instead.")
        return None


def choose_folder(cfg):
    current = Path(cfg["output"])
    v = ask(f"Save folder: {current}\n  Enter = keep | b = browse window | or paste a path: ")
    if not v:
        return current
    new = browse_folder(current) if v.lower() == "b" else v.strip("\"'")
    if not new:
        return current
    new = Path(new).expanduser()
    try:
        new.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"{Fore.RED}Cannot use that folder: {e}{Style.RESET_ALL}")
        return current
    cfg["output"] = str(new)
    save_config(cfg)
    return new


def download_menu(site, cfg):
    print(f"\n--- {site.label}: download ---")
    if site.tag_note:
        print(f"Note: {site.tag_note}")
    tags = ask("Tags (space separated): ").split()
    if not tags:
        print("No tags!")
        return
    try:
        limit = int(ask(f"How many posts? (max {MAX_POSTS}, default 100): ", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, MAX_POSTS))
    output = choose_folder(cfg)
    cbz = ask("Create CBZ archive? (y/N): ").lower() in ("y", "yes")
    download_media(site, cfg, tags, limit, output, cbz)


def api_menu(site, cfg):
    creds = cfg[site.key]
    while True:
        print(f"\n--- {site.label}: API settings ---")
        for field, title in site.fields:
            print(f"  {title}: {mask(creds[field]) if 'key' in field else (creds[field] or '(not set)')}")
        print(f"  {site.help}")
        print("\n1) Set / change credentials\n2) Test credentials\n3) Clear credentials\n0) Back")
        c = ask("> ")
        if c == "1":
            for field, title in site.fields:
                v = ask(f"{title} (Enter to keep current): ")
                if v:
                    creds[field] = v
            save_config(cfg)
            print(f"{Fore.GREEN}Saved.{Style.RESET_ALL}")
        elif c == "2":
            ok, msg = site.test(make_session(), creds)
            print((Fore.GREEN if ok else Fore.RED) + msg + Style.RESET_ALL)
        elif c == "3":
            for field, _ in site.fields:
                creds[field] = ""
            save_config(cfg)
            print("Cleared.")
        elif c == "0":
            return


def site_menu(site, cfg):
    while True:
        state = "API configured" if site.is_configured(cfg[site.key]) else "no API key"
        print(f"\n========== {site.label} ({state}) ==========")
        print("1) Download by tags\n2) API settings\n0) Back")
        c = ask("> ")
        if c == "1":
            download_menu(site, cfg)
        elif c == "2":
            api_menu(site, cfg)
        elif c == "0":
            return


def main():
    cfg = load_config()
    if Image is None:
        print(f"{Fore.YELLOW}Pillow missing -> images can't be converted to PNG. Run: pip install pillow{Style.RESET_ALL}")
    if FFMPEG is None:
        print(f"{Fore.YELLOW}ffmpeg missing -> webm/gif/other videos are kept in their original format (mp4 files are fine).{Style.RESET_ALL}")
    while True:
        print("\n========== chibanatoru Downloader ==========")
        for i, s in enumerate(SITES, 1):
            print(f"{i}) {s.label} downloader")
        print("0) Exit")
        c = ask("> ")
        if c == "0":
            break
        if c.isdigit() and 1 <= int(c) <= len(SITES):
            site_menu(SITES[int(c) - 1], cfg)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nBye.")
