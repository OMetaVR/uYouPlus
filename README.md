# uYouPlus builds

Automatic builds of [uYouEnhanced](https://github.com/arichornlover/uYouEnhanced), the maintained continuation of qnblackcat's (archived) uYouPlus, for:

- **SideStore / AltStore / LiveContainer / Sideloadly / TrollStore:** the `.ipa` on each [release](../../releases)
- **Jailbroken devices:** rootless (`iphoneos-arm64`) and rootful (`iphoneos-arm`) `.deb`s on the same release; they need uYou (`com.miro.uyou`) installed

Also available in the [Meta's Apps source](https://ometavr.github.io/ipa-source/source.json).

## How it works

```
Watch (every 3h, Ubuntu)
  upstream published a new release?  ── no ──▶ done
        │ yes
  decrypted YouTube <version it targets> in the base-ipas draft?
        │ no ──▶ opens a "Decrypted YouTube X needed" issue (you get notified)
        │ yes
Build (macOS)
  upstream at that tag + patches/*.patch + base IPA → IPA + .debs → GitHub release
        │
ipa-source picks up the new release within the hour
```

- **Upstream releases are the trigger**, not App Store updates. uYouEnhanced targets one YouTube version per release (`YOUTUBE_VERSION` in its Makefile), and the tweaks are often broken on newer YouTube versions.
- **Base IPAs** are stored in a *draft* release called `base-ipas`. Drafts are only visible to people with write access to the repo, so the decrypted YouTube IPAs aren't public.
- **Actions minutes**: this repo is public, so the macOS build is free. The first build compiles FFmpegKit (30–90 min); later builds use the cache.
- If a build fails, the watcher opens an issue and doesn't retry that tag until you re-run it.
- If upstream changes its `buildapp.yml`, the watcher opens an issue so `build.yml` can be checked against it (`upstreamWorkflowSha256` in `config.json`).

## Supplying a decrypted IPA

When the "needed" issue appears, get the decrypted YouTube IPA for that version (e.g. from iOSGods' Decrypted App Store) and run:

```sh
scripts/push-ipa.py ~/Downloads/YouTube.ipa
```

It checks the bundle ID and that the main binary and frameworks are decrypted, uploads it as `YouTube_<version>.ipa` to the `base-ipas` draft, and runs the watcher, which starts the build. `--no-build` uploads without running the watcher.

To build a version upstream doesn't target, upload it with `--no-build`, then run **Actions → Build** with the upstream tag and `youtube_version` set.

## Customizing

- `config.json` → `build`: bundle ID, app name, SDK version, YTUHD, iSponsorBlock, and whether to build `.deb`s.
- `patches/*.patch`: applied to upstream with `git apply` before building. Make them in a checkout of uYouEnhanced with `git diff > patches/name.patch`.
