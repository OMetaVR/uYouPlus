#!/usr/bin/env python3
"""Decide whether to build, run by the watch workflow.

Looks at upstream's latest published release. If this repo has no release for
that tag yet, it either starts a build (when the matching decrypted YouTube IPA
is in the "base-ipas" draft release) or opens an issue asking for that IPA.
Needs the gh CLI with GH_TOKEN and GITHUB_REPOSITORY set.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
REPO = os.environ["GITHUB_REPOSITORY"]
UPSTREAM = CONFIG["upstream"]
DRAFT_TAG = "base-ipas"
NEED_IPA_LABEL = "needs-ipa"


def gh(*args, check=True):
    p = subprocess.run(["gh", *args], text=True, capture_output=True)
    if check and p.returncode:
        raise SystemExit(f"gh {' '.join(args)} failed:\n{p.stderr}")
    return p


def gh_json(*args):
    return json.loads(gh(*args).stdout)


def upstream_file(path, ref):
    data = gh_json("api", f"repos/{UPSTREAM}/contents/{path}?ref={ref}")
    return base64.b64decode(data["content"])


def ensure_issue(title, body, label=None):
    issues = gh_json("issue", "list", "-R", REPO, "--state", "open", "--search", f'in:title "{title}"', "--json", "number,title")
    if any(i["title"] == title for i in issues):
        return
    args = ["issue", "create", "-R", REPO, "--title", title, "--body", body]
    if label:
        gh("label", "create", label, "-R", REPO, "--color", "D93F0B", "--force")
        args += ["--label", label]
    gh(*args)
    print(f"Opened issue: {title}")


def close_issues(label, comment):
    for i in gh_json("issue", "list", "-R", REPO, "--state", "open", "--label", label, "--json", "number"):
        gh("issue", "close", str(i["number"]), "-R", REPO, "--comment", comment)


def appstore_version():
    try:
        with urllib.request.urlopen(f"https://itunes.apple.com/lookup?id={CONFIG['appStoreId']}") as r:
            return json.load(r)["results"][0]["version"]
    except Exception:
        return "unknown"


def main():
    rel = gh_json("api", f"repos/{UPSTREAM}/releases/latest")
    tag = rel["tag_name"]
    makefile = upstream_file("Makefile", tag).decode()
    yt = re.search(r"^YOUTUBE_VERSION = (\S+)", makefile, re.M).group(1)
    print(f"Upstream {UPSTREAM} {tag} targets YouTube {yt}")

    wf_hash = hashlib.sha256(upstream_file(".github/workflows/buildapp.yml", tag)).hexdigest()
    if CONFIG["upstreamWorkflowSha256"] and wf_hash != CONFIG["upstreamWorkflowSha256"]:
        ensure_issue(
            f"Upstream build workflow changed ({tag})",
            f"`buildapp.yml` in {UPSTREAM} at `{tag}` no longer matches the one `build.yml` was based on.\n\n"
            f"Compare: https://github.com/{UPSTREAM}/blob/{tag}/.github/workflows/buildapp.yml\n\n"
            f"After updating `build.yml` if needed, set `upstreamWorkflowSha256` in `config.json` to `{wf_hash}`.",
        )

    if gh("api", f"repos/{REPO}/releases/tags/{tag}", check=False).returncode == 0:
        print(f"Already released {tag}")
        close_issues(NEED_IPA_LABEL, f"Built and released as {tag}.")
        return

    runs = gh_json("run", "list", "-R", REPO, "-w", "build.yml", "-L", "20", "--json", "displayTitle,status,conclusion")
    mine = [r for r in runs if r["displayTitle"] == f"Build {tag}"]
    if any(r["status"] != "completed" for r in mine):
        print(f"A build for {tag} is already running")
        return
    if any(r["conclusion"] == "failure" for r in mine):
        ensure_issue(f"Build failed for {tag}",
                     f"The build for upstream `{tag}` failed, so the watcher won't retry it automatically.\n\n"
                     f"Fix the cause, then re-run it: Actions → Build → Run workflow (upstream tag `{tag}`).")
        print(f"Previous build for {tag} failed; not retrying")
        return

    releases = gh_json("api", f"repos/{REPO}/releases?per_page=100")
    draft = next((r for r in releases if r["draft"] and r["tag_name"] == DRAFT_TAG), None)
    asset = f"YouTube_{yt}.ipa"
    if draft and any(a["name"] == asset for a in draft["assets"]):
        gh("workflow", "run", "build.yml", "-R", REPO, "-f", f"upstream_tag={tag}")
        print(f"Started build for {tag} with {asset}")
        return

    ensure_issue(
        f"Decrypted YouTube {yt} needed",
        f"Upstream released [`{tag}`](https://github.com/{UPSTREAM}/releases/tag/{tag}), which targets "
        f"**YouTube {yt}**. (Latest on the App Store: {appstore_version()}.)\n\n"
        f"Get a decrypted YouTube {yt} IPA and run:\n\n"
        f"```\nscripts/push-ipa.py /path/to/YouTube.ipa\n```\n\n"
        f"The build starts automatically and this issue closes once it's released.",
        label=NEED_IPA_LABEL,
    )


if __name__ == "__main__":
    main()
