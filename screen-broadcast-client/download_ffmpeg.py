"""
Download FFmpeg (ffmpeg.exe + ffprobe.exe) for the Screen Capture Client.

This downloads the "release essentials" build, extracts the binaries, and
places them in:
  - ./ffmpeg/            (used by build_client_exe.py to bundle into the .exe)
  - ./dist_client/ffmpeg/ (so the already-built ScreenCaptureClient.exe works)

Run:  python download_ffmpeg.py
"""

import os
import sys
import shutil
import zipfile
import tempfile

import requests

# Primary + fallback download URLs (Windows 64-bit essentials builds)
DOWNLOAD_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/GyanD/codexffmpeg/releases/download/2024-01-01-git/ffmpeg-2024-01-01-git-essentials_build.zip",
]

TARGET_DIRS = [
    os.path.join("ffmpeg"),
    os.path.join("dist_client", "ffmpeg"),
]

WANTED = {"ffmpeg.exe", "ffprobe.exe"}


def download_with_progress(url, filename):
    print(f"Downloading: {url}")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {pct:5.1f}%  ({downloaded:,} / {total:,} bytes)", end="")
        print()
    return filename


def main():
    print("=" * 60)
    print("FFmpeg downloader for Screen Capture Client")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp(prefix="ffmpeg_dl_")
    zip_path = os.path.join(tmp_dir, "ffmpeg.zip")

    # Download (try each URL until one works)
    downloaded = False
    last_error = None
    for url in DOWNLOAD_URLS:
        try:
            download_with_progress(url, zip_path)
            if os.path.getsize(zip_path) > 1_000_000:  # sanity: > 1 MB
                downloaded = True
                break
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"  Failed: {e}")

    if not downloaded:
        print("\nERROR: Could not download FFmpeg.")
        print(f"Last error: {last_error}")
        print("\nManual option:")
        print("  1. Download 'release essentials' from https://www.gyan.dev/ffmpeg/builds/")
        print("  2. Extract it and copy bin\\ffmpeg.exe into a folder named 'ffmpeg'")
        print("     next to ScreenCaptureClient.exe (i.e. dist_client\\ffmpeg\\ffmpeg.exe)")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return 1

    print(f"\nDownloaded archive: {os.path.getsize(zip_path):,} bytes")

    # Extract
    extract_dir = os.path.join(tmp_dir, "extracted")
    print("Extracting...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # Locate wanted binaries
    found = {}
    for root, _dirs, files in os.walk(extract_dir):
        for name in files:
            if name.lower() in WANTED:
                found[name.lower()] = os.path.join(root, name)

    if "ffmpeg.exe" not in found:
        print("ERROR: ffmpeg.exe not present in the downloaded archive.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return 1

    # Copy into all target directories
    for target in TARGET_DIRS:
        os.makedirs(target, exist_ok=True)
        for name, src in found.items():
            dst = os.path.join(target, name)
            shutil.copy2(src, dst)
            print(f"  -> {dst} ({os.path.getsize(dst):,} bytes)")

    shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\nDone! FFmpeg is ready.")
    print("  - Existing exe: dist_client\\ScreenCaptureClient.exe will now find ffmpeg.")
    print("  - To bundle it INTO a fresh exe, run: python build_client_exe.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
