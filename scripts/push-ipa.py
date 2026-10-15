#!/usr/bin/env python3
"""Upload a decrypted YouTube IPA for the build workflow, then start a build.

    scripts/push-ipa.py ~/Downloads/YouTube_21.20.4_decrypted.ipa
    scripts/push-ipa.py YouTube.ipa --no-build   # just store it

The IPA is checked (bundle ID, decrypted main binary and frameworks) and uploaded
as YouTube_<version>.ipa to the "base-ipas" draft release. Draft releases are
only visible to people with write access, so base IPAs aren't public. Needs the
gh CLI, logged in.
"""

import argparse
import json
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
DRAFT_TAG = "base-ipas"

LC_ENCRYPTION_INFO = 0x21
LC_ENCRYPTION_INFO_64 = 0x2C
FAT_MAGICS = {0xCAFEBABE: False, 0xCAFEBABF: True}  # value: 64-bit fat_arch


def cryptids(f):
    """Yield the cryptid of every slice in a Mach-O file object."""
    head = f.read(8)
    magic, = struct.unpack(">I", head[:4])
    if magic in FAT_MAGICS:
        nfat, = struct.unpack(">I", head[4:8])
        size = 32 if FAT_MAGICS[magic] else 20
        archs = [f.read(size) for _ in range(nfat)]
        offsets = [struct.unpack(">Q" if size == 32 else ">I", a[8:16] if size == 32 else a[8:12])[0] for a in archs]
        for off in offsets:
            f.seek(off)
            yield from cryptids(f)
        return
    f.seek(f.tell() - 8)
    start = f.tell()
    hdr = f.read(32)
    magic, = struct.unpack("<I", hdr[:4])
    if magic not in (0xFEEDFACE, 0xFEEDFACF):
        return
    ncmds, = struct.unpack("<I", hdr[16:20])
    f.seek(start + (32 if magic == 0xFEEDFACF else 28))
    for _ in range(ncmds):
        cmd, size = struct.unpack("<II", f.read(8))
        body = f.read(size - 8)
        if cmd in (LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64):
            yield struct.unpack("<I", body[8:12])[0]


def check_ipa(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        plist_name = next((n for n in names if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n)), None)
        if not plist_name:
            sys.exit("Not an IPA: no Payload/*.app/Info.plist")
        app = plist_name.rsplit("/", 1)[0]
        info = plistlib.loads(z.read(plist_name))
        if info["CFBundleIdentifier"] != CONFIG["baseBundleId"]:
            sys.exit(f"Bundle ID is {info['CFBundleIdentifier']}, expected {CONFIG['baseBundleId']}")

        binaries = [f"{app}/{info['CFBundleExecutable']}"]
        binaries += [n for n in names if re.fullmatch(re.escape(app) + r"/Frameworks/([^/]+)\.framework/\1", n)]
        encrypted = []
        with tempfile.TemporaryDirectory() as tmp:
            for name in binaries:
                out = Path(tmp) / "bin"
                with z.open(name) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                with open(out, "rb") as f:
                    if any(cryptids(f)):
                        encrypted.append(name)
        if encrypted:
            sys.exit("IPA is still encrypted:\n  " + "\n  ".join(encrypted))
    return info["CFBundleShortVersionString"]


def gh(*args):
    p = subprocess.run(["gh", *args], text=True, capture_output=True)
    if p.returncode:
        sys.exit(f"gh {' '.join(args)} failed:\n{p.stderr}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ipa", type=Path)
    ap.add_argument("--no-build", action="store_true", help="upload only, don't start a build")
    ap.add_argument("--repo", default="OMetaVR/uYouPlus")
    args = ap.parse_args()

    version = check_ipa(args.ipa)
    print(f"Decrypted YouTube {version}: OK")

    makefile = gh("api", f"repos/{CONFIG['upstream']}/contents/Makefile", "-H", "Accept: application/vnd.github.raw")
    target = re.search(r"^YOUTUBE_VERSION = (\S+)", makefile, re.M).group(1)
    if version != target:
        print(f"warning: upstream currently targets YouTube {target}, this IPA is {version}", file=sys.stderr)

    drafts = json.loads(gh("api", f"repos/{args.repo}/releases"))
    if not any(r["draft"] and r["tag_name"] == DRAFT_TAG for r in drafts):
        gh("release", "create", DRAFT_TAG, "-R", args.repo, "--draft", "--title", "Base IPAs (private)",
           "--notes", "Decrypted IPAs used as build input. Kept as a draft so it isn't public.")

    with tempfile.TemporaryDirectory() as tmp:
        named = Path(tmp) / f"YouTube_{version}.ipa"
        named.symlink_to(args.ipa.resolve())
        print(f"Uploading {named.name}…")
        gh("release", "upload", DRAFT_TAG, str(named), "-R", args.repo, "--clobber")

    if not args.no_build:
        gh("workflow", "run", "watch.yml", "-R", args.repo)
        print(f"Started the watcher; it builds if upstream needs YouTube {version}.")
        print(f"Follow it with: gh run list -R {args.repo}")


if __name__ == "__main__":
    main()
