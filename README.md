# vial-web (xcmkb)

Web build of Vial for XCMKB keyboards (per-key RGB, layer indicators, trackpad, OLED and Updates tabs),
forked from [vial-kb/vial-web](https://github.com/vial-kb/vial-web).

The Vial application itself (Python/PyQt5) lives in `vialgui/` — vendored from
[superxc3/vial-gui@xcmkb](https://github.com/superxc3/vial-gui/tree/xcmkb) at f737912 and maintained here
since — and is compiled to WebAssembly (CPython 3.11 + PyQt5 via Emscripten); there is no separate
JavaScript port. CI builds on every push and deploys `xcmkb` to GitHub Pages; `main` mirrors upstream.

## Building

```
git clone -b xcmkb https://github.com/superxc3/vial-web.git
cd vial-web
git clone https://github.com/vial-kb/via-keymap-precompiled.git
./fetch-emsdk.sh
./fetch-deps.sh
./build-deps.sh
cd src
./build.sh
```

CI caches `emsdk/` and a `prune-deps.sh`-trimmed `deps/` so only the first run pays the ~40 min toolchain build.

Output lands in `src/build`. It uses a pthread build, so the page must be served
cross-origin isolated (COOP/COEP headers); `coi-serviceworker.js` handles that on hosts
such as GitHub Pages that cannot set headers. WebHID requires Chrome/Chromium/Edge.

## Demo

*Try the demo* on the start page, or a link to `https://superxc3.github.io/vial-web/?demo`, runs the full app
without a keyboard. It uses `demo/sofleplus2-tps65-510h.json`, a recording of what a real board answers
(`vialgui/python/protocol/demo_device.py` replays it; edits last until the page reloads). To refresh it for a
new firmware, plug a board in and run:

```
python demo/capture-demo.py sofleplus2-tps65-510h
python demo/stock-keymap.py demo/sofleplus2-tps65-510h.json <firmware .elf>   # board has a personal layout
```

Everything in the recording is public. `capture-demo.py` prints what is on the board and warns about macros;
`stock-keymap.py` puts back the keymap and knob map the firmware ships with. A new file name also goes into
`DEMO_BOARD` in `src/index.html`.

## Firmware catalogue

`firmware/` holds the `.uf2` files offered by the *Updates* tab and `manifest.json`, which is generated
from them. Publishing a firmware, either way:

**From the browser (no local tools):** on GitHub open `firmware/` → *Add file → Upload files*, drop the
`.uf2` and, optionally, a same-named `.md` with the release notes, commit to `xcmkb`. CI regenerates the
catalogue and deploys (~2 min).

**Locally:** drop the same files into `firmware/`, run `python firmware/make-manifest.py` to see the result
(and commit the updated `manifest.json`), push `xcmkb`.

Rules the generator enforces:

- Keep QMK's file name (`xcmkb_<keyboard>_<keymap>.uf2`, e.g. `xcmkb_sofleplus2u_tps65-511h.uf2`).
- The firmware's USB product string must follow the naming rule (`SoflePLUS2 TPS65 Horizontal v5.11h
  Signature RGB` …) — the generator reads it out of the UF2 and groups files by board; the version must
  differ from the previous release or the *Updates* tab will not see an update.
- Release notes: `<same stem>.md` next to the UF2 — a short client-facing summary of what changed; the tab
  shows it for the selected version, the full history stays on the GitBook changelog.
- Older versions left in `firmware/` stay selectable for rollback; move files you no longer want offered
  into `firmware/archive/`, which is neither scanned nor deployed.
- A file that breaks a rule fails the CI build (see the Actions log) instead of being published.
