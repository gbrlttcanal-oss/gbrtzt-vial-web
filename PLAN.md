# vial-web (xcmkb) — plan & progress log

Goal: a web build of `superxc3/vial-gui@xcmkb` (per-key RGB, layer indicators,
trackpad tab, OLED tab, `.vil` save/restore of those) hosted on GitHub Pages.

## Key facts (non-obvious)

- vial-web is **not a JS rewrite**. `src/build.sh` copies `vialgui/python/*` (the Vial app,
  vendored from `superxc3/vial-gui@xcmkb` at f737912 on 2026-09-16 and maintained here since — the
  vial-gui repo is frozen, no desktop builds) into a CPython 3.11 + PyQt5 tree compiled to
  WebAssembly with Emscripten. Web-specific behaviour is behind `sys.platform == "emscripten"`
  and the tiny `vialglue` C module in `src/main.c`. The page footer's "Vial:" hash is the last
  commit that touched `vialgui/` (CI checks out with `fetch-depth: 0` for that).
- No other repository is cloned at build time except `vial-kb/via-keymap-precompiled`.
- The build is `-pthread -sPROXY_TO_PTHREAD`, so it needs `SharedArrayBuffer`, which needs
  `Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: require-corp`.
  vial.rocks gets these from Cloudflare. GitHub Pages cannot set headers, so
  `src/coi-serviceworker.js` (MIT, vendored) injects them client-side; it must be the first
  script in `index.html`.
- Branches: `main` = clean mirror of `vial-kb/vial-web`, `xcmkb` = custom work + default branch.
  Pages deploys only from `xcmkb`.
- A full toolchain build (emsdk + Qt 5.14 + CPython + PyQt5) takes ~40 min on `ubuntu-22.04`.
  `actions/cache` keeps `emsdk/` + a pruned `deps/` (see `prune-deps.sh`, which keeps exactly the
  paths `src/build.sh` links against) keyed on `version.sh` + build scripts + `patches/**`.
- On the very first visit the service worker is not yet controlling the page, so the runtime must
  not be started until `SharedArrayBuffer` exists; `index.html` gates the `main-*.js` load on that
  and coi-serviceworker reloads once it has taken control.
- Local Linux is not required; everything runs on `ubuntu-22.04` runners.

## Phases

### Phase 1 — fork & inspect  ✅ 2026-09-15
- [x] Fork exists (`superxc3/vial-web`), cloned to `C:\Users\User\vial-web`, `upstream` remote added
- [x] Read all build scripts, `main.c`, `worker.js`, `index.html`; located the single vial-gui reference

### Phase 2 — repoint to the fork  ✅ 2026-09-15
- [x] Workflow clones `superxc3/vial-gui@xcmkb`
- [x] Separate `deploy` job → GitHub Pages (re-runnable without rebuilding)
- [x] `du -sh` size report step (input for caching decision)
- [x] coi-serviceworker vendored, loaded first, copied into the build output
- [x] Favicon path made relative for the `/vial-web/` project URL
- [x] `main` reset to upstream; work moved to `xcmkb`; default branch and Pages
      environment (no branch restriction) set on GitHub
- [x] First green build of `xcmkb` (run 34930649973, build 40m 2s, deploy 10s) → https://superxc3.github.io/vial-web/

### Phase 3 — verify in the browser (Chrome/Edge + keyboard)
- [x] Start button enables (Python booted in the WASM worker), `crossOriginIsolated: true` under the
      service worker — verified in Chrome 152 on 2026-09-15
- [x] First-visit alert "SharedArrayBuffer is not defined" (runtime started before the SW reload) —
      fixed by gating the runtime load in `index.html`
- [ ] Qt UI appears after *Start Vial* + device pick
- [x] WebHID chooser lists the keyboard; keymap edits and lighting effect changes reach the
      firmware (user, 2026-09-15). The earlier "not detected" was the first-visit alert state.
- [x] Keymap tab baseline
- [x] Lighting tab: per-key RGB, indicators — colour pickers used `QColorDialog.exec_()` (nested
      event loop → `emscripten_sleep` error on WASM); converted to `show()` + `finished` like the
      upstream underglow picker (`vial-gui@5466196`). User confirmed working.
- [x] Trackpad tab — verified on macOS Chrome (user, 2026-09-16). Sliders/checkboxes only reach the
      firmware on *Apply Settings to Keyboard*; same as desktop
- [x] OLED tab + OLED layer-name field on Keymap (user confirmed)
- [ ] `.vil` save/load round-trip including trackpad/RGB data — save to Desktop works; save to
      Documents failed in the Windows dialog ("C:/Users/User/Documents/-web.vil File not found").
      Documents is not OneDrive-redirected on that PC. Added `suggestedName` (keyboard product
      name) to the save picker; differential test pending: does vial.rocks (same code) fail too?
- [x] Custom-colour presets and indicator config survive a reload (user confirmed)

### Phase 3b — fixes in `vial-gui@xcmkb` (as surfaced by Phase 3)
- [x] Persistence of the app data dir. Chosen design (prototyped live in Chrome against the
      deployed page, verified across a reload): `index.html` mounts Emscripten's IDBFS on
      `/home/web_user/.local/share` and loads it before `webmain.main`; `vialglue.fs_sync()`
      (new, `main.c`) flushes it; vial-gui calls `util.persist_app_data()` after its two JSON
      writes (`vial-gui@f2f1cb7`). No change to the file-based code itself.
      Gotcha: mounting at `/home/web_user` fails with `VersionError` — Qt's wasm QSettings owns
      an IndexedDB database of that name via `emscripten_idb_async_*` (IDBStore v22 vs IDBFS v21).
- [ ] Anything else found in testing

### Phase 4 — make iteration cheap
- [x] `actions/cache` for `emsdk/` + pruned `deps/` (`prune-deps.sh`) — verified: run 34939455331
      took 1m 31s on a cache hit (vs 40 min)

### Phase 5 — web-first feature work (vial-gui stays the single codebase)
- Decisions (2026-09-15): web is the primary distribution; desktop builds are kept only for
  firmware flashing. No manual version bumps for web — the page footer's commit hashes identify
  a build. Rules for new code: no nested event loops (`exec_()`), non-blocking dialogs, file
  I/O only through `vialglue`, keep it light.
- [x] Keycode search: new first tab "Search" in the keycode picker (`vial-gui@6508fc8`).
      Matches label / QMK ID / alias / description, grouped by the tab the keycode lives in,
      ranked exact > prefix > contains > alias > words, capped at 80, 150 ms debounce.
      Headless-tested on desktop (offscreen Qt); verify look and feel on web.

- [x] Tooltips on web (`vial-gui@f737912` + this commit). Root cause: Qt 5.14's WASM compositor
      activates every new window, tool tips included, and QTipLabel hides itself the moment its
      window is deactivated — so a tip flashed and vanished, and the main window was left inactive
      (no more tips until a click). Qt 5 never fixed it; Qt 6 rewrote the compositor and added a
      `Q_OS_WASM` case in qtooltip.cpp (QTBUG-94583 is still open). `patches/qt/wasm-tooltips.patch`
      backports both: tool-tip windows never take activation in `QWasmCompositor::notifyTopWindowChanged`,
      plus the Qt 6 qtooltip.cpp condition. `WA_AlwaysShowToolTips` on the main window is kept as
      insurance. Changing `patches/**` invalidates the deps cache once (~40 min).

### Phase 6 — firmware flashing from the web page (UF2 / RP2040)  — to-do, decided 2026-09-16
Goal: a client updates the keyboard firmware from the Pages URL without installing anything.
Facts that shape it (verified 2026-09-16):
- All xcmkb boards are RP2040 on the ROM UF2 bootloader (BOOTSEL: VID 0x2E8A PID 0x0003); a firmware
  UF2 is ~200 KB, family ID 0xE48BFF56, ~100 KB of flash.
- Two browser routes, both Chrome/Edge-only like WebHID: **WebUSB → PICOBOOT** (bootrom vendor
  interface; WinUSB auto-binds on Windows via WCID, macOS works, Linux needs a udev rule) using the
  MIT-licensed `piersfinlayson/picoflash` `pkg/` (~50 KB ES modules) + its `js/uf2/uf2.js`; or
  **File System Access → the RPI-RP2 drive** (no driver, but the user must pick the drive and Chrome
  writes through a `.crswap` file, so the board reboots mid-write and `close()` throws after a complete
  write — treat that as success). WebUSB primary, FS Access fallback, plain download as last resort.
- The host cannot currently reboot the board into the bootloader: every xcmkb keymap is
  `VIAL_INSECURE = yes` and vial-qmk compiles `id_bootloader_jump` only for secure builds
  (`quantum/via.c`). *Security → Reboot to bootloader* is therefore a no-op, and on the web build it then
  raises (`Keyboard.reset()` calls `dev.close()`, which the emscripten `hiddevice` in `hidproxy.py` lacks).
  Interim: double-tap reset (enabled in every config.h) or a `QK_BOOT` key.
- Split board → both halves need the UF2. EE_HANDS builds: either half can be the USB master;
  MASTER_LEFT builds: the right half only via double-tap reset.
- The page is COEP `require-corp`: firmware must be same-origin or sent with
  `Access-Control-Allow-Origin` (GitHub Pages does; Drive/Dropbox/GitBook attachments and
  `github.com/…/releases/download/` do not). Decision: same-origin `firmware/` in this repo.
- WebUSB and file pickers exist only on the page thread → the flasher is JS in `src/`; Python gets a thin
  tab plus one `vialglue` call, on the same postMessage pattern as the `.vil` dialogs (keeps the
  user-activation window).
- Board identification (checked 2026-09-16): every keymap sets a USB product string with trackpad,
  orientation, version and — from v5.04 — the PCB batch word (`Legendary` = ano, `Legendary RGB`,
  `Signature RGB` = 2u, none = sofleplus2), e.g. `SoflePLUS2 TPS65 Horizontal v5.10h Signature RGB`.
  WebHID exposes it as `productName` at device pick, before Python boots. Ambiguous for older firmware:
  v5.04–v5.09 `Legendary` covers ano *and* legendaryrgb, ≤ v5.03 has no batch word. VID/PID are shared
  (`0xFC32:0x0287`; only 510h/tps43-510 moved to `0x0288`/`0x0289`) and the Vial UID names the layout,
  not the batch (legendaryrgb shares sofleplus2's), so a manual fallback list stays necessary.

- [x] A — catalogue (2026-09-16): `firmware/manifest.json` + `*.uf2` in this repo, copied to `src/build/firmware/` by
      `src/build.sh`. One entry per *board* (family/trackpad/orientation/batch): `{id, name, batch_label,
      match: {product: [regex…], fw_id?, uid?}, latest, firmware:[{version, date, file, sha256, notes,
      changelog_url}]}`. Drop workflow: keep QMK output names (`xcmkb_<variant>_<keymap>.uf2`, which
      encode board/trackpad/orientation/version), run `firmware/make-manifest.py` (derives board +
      version from the name, adds sha256; you fill date + notes), push to `xcmkb` or use GitHub's
      "Upload files" → CI ~1.5 min → live. Keep the last 2–3 versions per board for rollback.
- [x] A2 v1 (download/changelog/warnings/instructions; Flash button pending B) — **Updates** tab (UX decided 2026-09-16; Qt, after OLED, web build only, titled
      `Updates (beta)`, tab label becomes `Updates *` when an update is found via `setTabText`).
      Detection in Python from `device.desc["product_string"]` with the format below → board +
      version → compare with manifest `latest` by equality; ambiguous/unknown → board combo box.
      Contents: Your keyboard / Latest firmware / Status / release notes; buttons *Download update
      (.uf2)* (new `vialglue.download_file` → JS `<a download>`, same-origin), *Flash from browser
      (beta)* (→ B's overlay via `vialglue.flash_firmware(entry_json)`; hidden until B exists),
      *View changelog* (existing `open_url` bridge → GitBook firmware changelog); warning
      "Updating may reset your keymap — save your layout first; unsaved changes will be lost";
      both-halves instructions (save .vil → double-tap reset on the USB half → RPI-RP2 → copy/flash →
      unplug, cable directly into the OTHER half (TRRS carries no USB) → repeat with the same file →
      back to the usual half, Start Vial, load .vil). Manifest reaches Python by `build.sh` copying
      `firmware/manifest.json` into the preloaded `usr/local/` (read like `qmk_settings.json`).
      Delivery: A → tab v1 (download/changelog/warnings/instructions) → B → Flash button.
- [x] A3 (2026-09-16, comment added; folders still uncommitted) — firmware repo: naming-rule comment above `#define PRODUCT` in
      `sofleplus2/keymaps/{tps65-510,tps43-510,tps65-510h}/config.h` (text agreed 2026-09-16; the other
      variants' 510 keymaps optional). Commit the three untracked 510 keymap folders while there.
- [x] B (2026-09-16; drive route verified on Windows by the user, USB route pending a PC with WinUSB / the macOS test) — page-side flasher: vendor picoflash `pkg/` + `uf2.js` into `src/flash/` (MIT notice
      kept, copied by `build.sh`); "Update firmware" on the start screen + an overlay like `#unlock`;
      pre-flight checks (family ID, address range, size cap, sha256 vs manifest); WebUSB erase/write with
      progress, then reboot; FS Access and download fallbacks; bootloader-entry and "flash the other half"
      instructions. Doubles as the recovery path when Vial cannot connect.
      Built as: `src/flash/` (picoflash `pkg/` at 6783554 minus its broken `index.js`, `uf2.js`,
      our `flasher.js`), `#flash` overlay in `index.html`, `vialglue.flash_firmware(entry_json)`,
      *Update now* button in the tab. Flow: fetch → size/SHA-256/UF2 family+range checks → user
      double-taps reset → WebUSB chooser ("RP2 Boot") → exclusive access, exit XIP, erase, 4 KB
      chunked writes with progress, enter XIP + read-back verify, reboot → "Update the other half"
      (same image) / "Finish" (`location.reload()`). Not done: the start-screen entry point (Vial
      must connect first, so a board whose firmware is dead still needs the RPI-RP2 drag route).
- [x] C (2026-09-16: `quantum/via.c` guard changed in the local vial-qmk tree, uncommitted; takes effect
      with the next firmware build) — firmware (vial-qmk): allow `id_bootloader_jump` in INSECURE builds (drop the guard or handle
      it in `raw_hid_receive_kb`). Only boards flashed with this or newer can be rebooted by the host;
      older ones go through B manually once.
- [ ] C2 — firmware identity, same release as C: one define per keymap (`XCMKB_FW_ID
      "sofleplus2u/tps65h/5.11h"`) returned by a new VialRGB GET `0x54`; manifest `match.fw_id` takes
      precedence over the product-string rules. Also write the product-string format below into
      `vial-qmk/keyboards/xcmkb/README.md` so firmware work keeps to it.

Product-string format (decided 2026-09-16; it is `#define PRODUCT` in each keymap's `config.h` of the
firmware repo, overriding `keyboard_name` in keyboard.json — not vial.json, nothing on the web side):
`<Family> [<TPS43|TPS65>] [Horizontal] v<major>.<minor>[<letter>] [<batch words>] [Beta …]`
- Family `SoflePLUS` = sofleplus1 (batch 0, `SoflePLUS v1.10`, PID 0x028A); `SoflePLUS2` = the rest.
- Batch words are the trailing phrase, matched whole (`Legendary` is a prefix of `Legendary RGB`):
  none = sofleplus2 (latest batch), `Legendary` = sofleplus2ano (batch 1), `Legendary RGB` =
  sofleplus2legendaryrgb (batch 1), `Signature RGB` = sofleplus2u (batch 2).
- `Horizontal` always pairs with the `h` version suffix (`Horizontal v5.10h`); `Beta …` is never latest.
- Verified 2026-09-16: all four sofleplus2 variants × tps43-510 / tps65-510 / tps65-510h conform.
  Scope decision: auto-detect and the update prompt apply to v5.10 and later only; older boards
  (≤ v5.09 `Legendary` ambiguous, ≤ v5.03 no batch word) pick from a narrowed list. CornePLUS/CornePLUS2
  have no `PRODUCT` define (no version) → manual list unless one is added in this format.
- [ ] D — Vial UI integration (vial-gui@xcmkb + vial-web): `hiddevice.close()` no-op; web-only "Firmware"
      tab replacing the hidden vibl updater on emscripten, listing manifest entries that match the keyboard
      UID (page fetches the manifest, hands JSON to Python like `get_device_desc`); "Save layout first";
      *Update* → `main.lock_ui()` → `keyboard.reset()` → `vialglue.flash_firmware(entry)` → B's overlay with
      the file preselected. MVP ends with `location.reload()`; later rebind `g_device` from
      `navigator.hid.getDevices()` / the `connect` event, refresh the device desc, `on_click_refresh()`,
      restore the backed-up layout; then prompt for the second half.
- [ ] E — verify and document: Windows 11 Chrome/Edge (WinUSB auto-bind, plus Zadig / FS-Access fallback),
      macOS Chrome, both halves, EE_HANDS vs MASTER_LEFT, wrong-file rejection, unplug mid-flash (bootrom is
      safe, retry); client steps in the GitBook.

Estimate: A 1–2 h, B ~1 day, C 30 min + a firmware release, D 1–2 days, E ½ day. B is the first milestone
(works for every existing board today); C + D turn it into the one-click flow.

### Later / optional
- [x] Fork notice: start screen `#notice` + About box (`vial-gui@feff418`) say it is a customised
      XCMKB build, not affiliated with the Vial project, with upstream/source/license links;
      tab title "Vial Web (XCMKB)"
- [x] Links inside the Qt UI work: Qt's openUrl is `window.open()` in the worker, which upstream
      stubbed as a no-op; `worker.js` now posts `open_url` and the page opens a new tab
- ~~`repository_dispatch` from vial-gui CI~~ — obsolete, the app is vendored (2026-09-16)
- [ ] Periodic `git merge upstream/main` into `xcmkb`; upstream vial-gui changes now have to be
      ported by hand into `vialgui/python`

## Log

- 2026-09-15 — Phases 1–2 done. Pushed `01ed96d` (repoint + Pages + coi-serviceworker) then
  `465497b` (deploy from `xcmkb`). Fork Actions enabled, default branch → `xcmkb`,
  Pages source → GitHub Actions, `github-pages` env → no branch restriction.
  Waiting on run 34930649973.
- 2026-09-15 — Run 34930649973 green (build 40 min), Pages live. User hit the first-visit
  SharedArrayBuffer alert and reported the keyboard not being detected. Verified in Chrome that the
  deployed page is cross-origin isolated and boots Python after the SW reload; the alert was the
  runtime starting before that reload. Pushed: gated runtime load, `prune-deps.sh`, dependency
  cache in CI. HID detection still open pending user details.
- 2026-09-15 — User confirms detection + keymap + lighting effect work. Prototyped persistence in
  the live page (IDBFS mount under `.local/share`, found the `/home/web_user` DB-name collision
  with Qt QSettings), then implemented: `vial-gui@f2f1cb7` + this commit. Useful debugging
  channel: with the page booted, `PThread.runningWorkers[0].postMessage({cmd:"py", payload})`
  runs Python in the worker and `print()` lands in the DevTools console.
- 2026-09-15 — Colour pickers fixed (`exec_()` → non-blocking), persistence confirmed by user,
  cache hit brings CI to ~1.5 min. Open: `.vil` save into Documents fails in the Windows dialog
  while Desktop works; added a suggested filename, awaiting a vial.rocks comparison.
- 2026-09-15 — Fork notice added (start screen + About), About-box links made to work on web
  (`open_url` bridge). User plans to share https://superxc3.github.io/vial-web/ with clients.
- 2026-09-15 — Keycode search shipped in vial-gui; this push rebuilds vial-web against it.
- 2026-09-15 — Search field narrowed. Tooltips: WA_AlwaysShowToolTips alone made them flash and
  vanish; traced to window activation in the 5.14 WASM compositor, backported a fix as a Qt patch.
- 2026-09-16 — Trackpad tab confirmed working on macOS (the settings were not applied because
  *Apply Settings to Keyboard* had not been pressed; no bug). UF2 flashing plan recorded as Phase 6
  (to-do, no code yet); hosting decided: same-origin `firmware/` in this repo.
- 2026-09-16 — Auto-detect of board/version for the update prompt designed: product string now, `0x54`
  firmware ID later; recorded as Phase 6 A2/C2.
- 2026-09-16 — Update UX decided: an *Updates (beta)* tab after OLED (asterisk when available, download /
  flash / changelog, keymap warning, both-halves instructions); firmware drops go into `firmware/`.
- 2026-09-16 — Phase 6 A/A2/A3 built: `firmware/` with 10 v5.10 UF2s + `make-manifest.py` (reads the
  product string out of each UF2's USB descriptor, so the catalogue matches what the board announces),
  `build.sh` preloads the manifest and serves `firmware/`, `vialglue.download_file` bridge, and the
  *Updates (beta)* tab in vial-gui (`editor/updates.py`; headless-tested against the real manifest for
  exact hit / rule hit / too-old / unknown / manual pick). Needs vial-gui pushed before vial-web rebuilds.
- 2026-09-16 — Decision: stop maintaining the vial-gui repo. Its Python app (102 files, 796 KB) and
  two JSON resources are vendored into `vialgui/`; CI no longer clones vial-gui. The Updates tab
  (`vialgui/python/editor/updates.py`) ships with this commit.
- 2026-09-16 — Updates tab polish (not pushed yet): status glyph/colour (green tick, amber warning, grey
  question mark), board list batch-first ("Batch 1: Legendary RGB - TPS65"; batches = PCB generations,
  hint shown under the list), release notes from `<uf2 stem>.md` sidecars, `firmware/archive/` for
  files to stop offering (older versions still in `firmware/` stay selectable for rollback).
  Decision: skip the drag-to-RPI-RP2 UX as the target; next is B (*Update now*, WebUSB) + C.
- 2026-09-16 — Phase 6 B built (in-browser WebUSB update) together with the tab polish; pushed for a
  hardware test on the deployed page. Unverified until then: picoflash on this bootrom (exit/enter
  XIP + read-back), WinUSB auto-bind on Windows, macOS claim while RPI-RP2 is mounted.
- 2026-09-16 — First hardware run of B hung after the device pick (no timeout in WebUSB). Rewrote the
  flasher to picoflash.org's proven sequence (no exclusive-access command; read-back after exit XIP,
  not enter XIP), per-step timeouts, picoboot's console trace mirrored into the overlay log, interface
  reset + disconnect on error. Added the automatic path: *Update now* sends VIA id_bootloader_jump
  (`Keyboard.reset()`, `hiddevice.close()` no-op added), the page watches the WebHID disconnect and
  auto-selects an already-authorised RP2 Boot device (`Picoboot.getDevices`); otherwise double-tap +
  chooser. Firmware side: via.c guard dropped (Phase C) — needs a firmware release to reach boards.
- 2026-09-16 — Second hardware run (Windows): WebUSB `claimInterface` never returned because Windows
  had not bound WinUSB to RP2 Boot (yellow warning in Device Manager; Zadig fixes that PC). Added the
  driver-free route to the overlay: *Copy to RPI-RP2 drive* (File System Access API: pick the drive,
  verify INFO_UF2.TXT, write the UF2; a close() failing after a complete write = the board rebooted).
  Connect timeouts now explain the driver situation per OS and say to reload before retrying (a hung
  claim leaves the device half-open in the tab). QK_BOOT as a key works on current firmware; the
  host-side reboot needs the next firmware build.
- 2026-09-16 — *Write to RPI-RP2 drive* verified by the user on Windows (`9176d26`). User rebuilt tps65-510h
  from the vial-qmk tree with the via.c change (09:20 build). Flow change: after an automatic reboot the
  page auto-runs the USB route only once USB has succeeded in that browser (`localStorage`
  `xcmkb_flash_usb_ok`); otherwise it shows the two buttons without asking for a double-tap.
- 2026-09-30 — Phase 8 (demo mode) and matrix-tester sounds written and desktop-tested, not committed. The board
  on hand runs tps65-510h with a personal layout, so the published recording waits on a stock tps65-510
  capture. Knob testing needs firmware support: proposed as Phase 9.

### Phase 7 — `.vil` load on the web: the "different keyboard" prompt crashes — decided 2026-09-20
Facts (verified 2026-09-20):
- `KeymapEditor.restore_layout` (`keymap_editor.py:174`) asks with `QMessageBox.question()`, a blocking
  dialog = nested Qt event loop. Qt 5.14's `QEventLoop::exec()` implements a nested loop on WASM with
  `emscripten_sleep(1)` (QTBUG-70185), which needs ASYNCIFY; our `-pthread -sPROXY_TO_PTHREAD` build has
  none, so Emscripten 3.1.10's stub throws "Please compile your program with async support …". The throw
  escapes the worker's `onmessage`, the page re-throws it as an `ErrorEvent` and `window.onerror` alerts
  `Uncaught [object ErrorEvent]`. The box is drawn (`exec()` shows first), but the frame that would call
  `keyboard.restore_layout()` is gone, so Yes does nothing. Same class as the `QColorDialog.exec_()` bug
  of Phase 3; upstream vial-gui has the identical code.
- What is compared is the Vial UID (`VIAL_KEYBOARD_UID`, `keyboard_comm.py:167`, saved as `"uid"`), not
  the USB product string. In vial-qmk it is per keymap and has changed between versions of the same board
  (sofleplus2 tps65-508h 91C4…, -509h 2E77…, -510h 4F8B…, -510 6BE4…; sofleplus2u tps65-510 ADAA…;
  corneplus2 5C0D…), so the Updates-tab flow (save .vil → flash → load .vil) triggers the prompt on the
  same physical board. Matrices: sofleplus2 10×7, corneplus2 8×6.
- [x] A (2026-09-20, incl. `qmk_settings.py`) — non-blocking prompt: `QMessageBox` + `setModal(True)` + `finished` (pattern of
      `rgb_configurator.py:227` / `webmain.show_exception_box`); the restore runs in the callback, then a
      new `KeymapEditor.layout_restored` signal → `MainWindow.rebuild()` (today `on_layout_loaded` and
      `on_layout_load` call `rebuild()` synchronously right after; with an async answer that would run
      before the load and leave the other tabs stale). Same fix for `qmk_settings.py:224` (reset question).
- [x] B (2026-09-20; `KeymapEditor.layout_matches`, checked headless on Windows Qt — offscreen/minimal
      QPA segfault on a bare `QMessageBox.show()` with the PyQt5 5.15.11 wheel, so use `QT_QPA_PLATFORM=windows`) — warn on layout shape, not UID: compare layers/rows/cols/encoder count of the `.vil` with the
      connected keyboard; a Sofle file from any firmware version loads silently, a Corne file still warns.
      (Alternative/addition, firmware side: one fixed UID per board family, never changed again — only
      helps boards on new firmware; B helps the ones already shipped.)
- [x] (2026-09-20) `index.html` `window.onerror` shows `error.message` for an `ErrorEvent` instead of
      `[object ErrorEvent]`.
- Later, same class, not in scope: `main_window.py:327/333/441` (`QMessageBox.warning`, `msg.exec_()`),
  `textbox_window.py:87/97` (macro text import/export needs the `vialglue` file bridge).

### Phase 8 — demo mode: browse Vial without a keyboard — go-ahead 2026-09-30 (edits allowed, Chrome/Edge only)
Goal: a *Try the demo* button on the start page (and a shareable `?demo` link) that opens the full Vial UI
on a virtual SoflePLUS2 TPS65 v5.10 (`sofleplus2/keymaps/tps65-510`), so clients can see the keymap,
lighting, trackpad and OLED tabs before buying or connecting.

Facts (verified 2026-09-30):
- Every read and write in the app goes through `Keyboard.usb_send(dev, 32-byte request)` → `dev.write()` /
  `dev.read()` (`util.hid_send`). The custom tabs (per-key RGB, indicators, trackpad, OLED) are probed
  inside `Keyboard.reload_persistent_rgb` through VialRGB GET sub-commands. So a fake `dev` that answers
  those requests runs the whole app unchanged. The layout definition is part of those answers.
- The existing `VialDummyKeyboard`/`DummyKeyboard` (desktop *Load dummy JSON…*, hidden on web) is a blank
  KC_NO keymap with 4 layers and no custom features, so it is not usable as a showcase. Making it one would
  mean overriding every `Keyboard` method and keeping that copy in step with the protocol.
- The keyboard's state cannot be rebuilt from the firmware source alone. The keymap is in `keymap.c` (78 KB,
  custom defines), and the state of the custom features (RGB, indicators, trackpad, OLED) is set by firmware
  code at EEPROM init, not by tables. A one-time capture from a real board is exact and much simpler.
- Web startup: `index.html connect()` → WebHID pick → `_vialglue_set_device_desc` → `webmain.main`.
  `MainWindow.__init__` calls `find_vial_devices` once (`on_click_refresh`), and on web `hid.enumerate()`
  probes the WebHID device. A demo must therefore be selected before `MainWindow` is created, and it must
  bypass `hid.enumerate()`.
- These screens read from the board again after a write, so replaying the capture alone would undo demo
  edits: QMK Settings (`rebuild` re-reads everything, and a `.vil` load triggers `rebuild`), *Reset*;
  *Revert* in Tap Dance / Combos / Key Overrides / Alt Repeat (`reload_dynamic`) and in Macros
  (`reload_macros`); Lighting `update_from_keyboard` (`reload_rgb`). Keymap, encoders, trackpad, OLED and
  per-key colours work from the Python-side copy after the load.
- tps65-510: `lighting: vialrgb`, matrix 10×7, 8 custom keycodes, `VIAL_INSECURE`, PRODUCT
  `SoflePLUS2 TPS65 v5.10`, UID `6BE4…`. No board was connected to this PC on 2026-09-30. `hidapi` and
  PyQt5 5.15.11 are installed locally (Python 3.14.3), so the capture and a desktop test can run here.

Plan:
- [x] A — `demo/capture-demo.py` (desktop, run once per firmware release). Opens the connected Vial board
      with the vendored code (`vialgui/python` on `sys.path`, hidapi) and wraps the device to record every
      request → response. Runs `Keyboard.reload()` (which covers the custom tabs), plus
      `get_unlock_status`/`get_unlock_keys`/`matrix_poll`. Writes `demo/<board>.json`:
      `{desc: {vendor_id, product_id, product_string, …}, captured, responses: {request_hex: response_hex}}`
      (tens of KB). Prints a summary (layers, non-empty macros / tap dances / combos) and warns that
      whatever is on the board, macros included, becomes public in the demo.
- [x] B — `vialgui/python/protocol/demo_device.py`: `DemoDevice` (`write`/`read`/`close`, like the web
      `hiddevice`) answers from the capture. It keeps state for the SET→GET pairs listed above (QMK
      settings, dynamic entries, macro buffer, VialRGB mode; keymap buffer and encoders too, since that
      is cheap), so edits stick for the session. An unknown request is echoed back (VIA's reply to a
      SET) and logged, and the bootloader jump is ignored.
- [x] C — `vial_device.VialDemoKeyboard(VialKeyboard)`: desc taken from the capture, path `/demo/<name>`,
      `open()` → `Keyboard(DemoDevice(...))`, title `"<product> [demo]"`. `util.find_vial_devices`
      returns only that when demo mode is set; the demo-mode flag is set by `webmain.main(app, demo=name)`
      before `MainWindow` is created.
- [x] D — `MainWindow` in demo mode: a banner above the tabs ("Demo — no keyboard connected. Edits stay in
      this browser tab only; *Save current layout…* still exports a .vil"). Hide the Security menu, the
      Matrix tester and the Updates tab, because each of these needs a physical board.
- [x] E — page: a *Try the demo (no keyboard)* button under *Start Vial*, enabled at `notify_alive`.
      `?demo` in the URL starts it without a click, so the GitBook or shop can link straight in.
      `startDemo()` = `mountAppData()` + `webmain.main(qtApp, demo="sofleplus2-tps65-510")`, with no
      WebHID. `layoutFileName()` uses the demo product name, and `flash_firmware` is ignored in demo mode.
      `build.sh` copies `demo/*.json` into the preloaded `usr/local/demo/`.
- [ ] F — test before pushing: run the vendored app on desktop (`QT_QPA_PLATFORM=windows`) in demo mode
      against the capture. Click through every tab; check that QMK Settings *Save* survives a `.vil` load,
      that the Revert buttons work, and that `.vil` save/load round-trips. Then push, wait for CI
      (~1.5 min) and verify in Chrome, including the `?demo` link on a first visit (the coi-serviceworker
      reload must keep the query string).

- [x] G — matrix tester sounds (asked 2026-09-30, folded in): a *Sound* checkbox (web only, remembered in
      QSettings) and a tone when a key newly registers: a short high beep if exactly one key is down, a lower
      double beep if two or more are down at once (a short, a ghost, or a roll). Only keys in the layout
      count. `util.play_sound()` → new `vialglue.play_sound(name)` (`main.c`) → the page plays it with
      WebAudio. The matrix tester stays hidden in demo mode.
- [x] H — the published recording is `demo/sofleplus2-tps65-510h.json` (the page's `DEMO_BOARD`). The user decided
      2026-09-30 that 510 vs 510h does not matter, since only the trackpad rotation differs, so the demo keeps
      the board's own identity. The board's personal keymap was replaced by the stock one with the new
      `demo/stock-keymap.py`: it reads `keymaps`/`encoder_map` out of the firmware `.elf` and rewrites the
      keymap-buffer and encoder answers, KC_TRNS past the compiled layers (as `dynamic_keymap_reset` does);
      OLED layer 8's `GAME` label went back to the firmware default `L8   `. Verified through the app: thumbs
      MO(1)/MO(2), knobs per `keymap.c` (the map is stored {cw, ccw}, Vial answers ccw first), layer 8
      transparent, and no macros, tap dances, combos, key overrides or alt-repeat keys. Lighting, trackpad
      and QMK settings stay as recorded from that board.

Status 2026-09-30 (not committed, not pushed):
- A–E and G are written. Tested on the desktop (`QT_QPA_PLATFORM=windows`, harness in the session scratchpad)
  with the real `MainWindow`: 11 tabs, Matrix tester / Updates / Security hidden, banner shown, and 13 checks
  passed: keymap, encoder, QMK setting (survives the `rebuild` a .vil load triggers; Reset restores it),
  tap dance, combo, macro, VialRGB mode/speed, sleep timeout, trackpad settings/layers, OLED names, and a
  `.vil` load through `on_layout_loaded`. The only request without a recorded answer was `09` (lighting
  save; echoing it is right). Sound triggering was tested with simulated matrix scans. The page's scripts
  pass `node --check`. The WASM build itself can only be tested after CI.
- Capture taken (363 answers, identical in two passes) from the board on this PC. That board runs
  **tps65-510h** (`SoflePLUS2 TPS65 Horizontal v5.10h`, PID 0x0288, UID 4F8B…), not tps65-510. Its
  `keymap.c`/`vial.json` and the compiled default keymaps are byte-identical to tps65-510's, so the content
  would match. It is also **personalised**: 9 keys in layers 0–3 differ from the compiled default (layer
  keys, e.g. MO(1)→MO(2)), layer 8 is a gaming layer (OLED name `GAME`), and the knob map differs. Kept
  as the untracked `demo/raw-510h.json` for testing only; what is published is the stock version (H).
- Next firmware release: record any board (`capture-demo.py`), then `stock-keymap.py` with that release's .elf.
- Flashing resets a board to stock: vial-qmk's `via_eeprom_is_valid` compares a random per-build
  `BUILD_ID` (`util/build_id.py`), so any newly flashed build wipes the saved layout.
- Chrome/Edge only, as decided: `show_error` hides the demo button along with *Start Vial*.

### Phase 9 — knob (encoder) test in the matrix tester — proposed 2026-09-30, needs a firmware release
Facts (verified 2026-09-30): the matrix tester reads `VIA_SWITCH_MATRIX_STATE`, which carries only the key
matrix. The knobs are not in it (they show as widgets with `encoder_idx`/`encoder_dir` but no row/col), and
no firmware command reports knob turns to the host. In vial-qmk, every knob step from both halves passes
through `encoder_handle_queue()` (`quantum/encoder.c:30`) on the USB half, so one core change covers all
XCMKB boards. Custom GETs are dispatched in `quantum/vialrgb.c` (`vialrgb_get_value`); 0x50–0x53 are taken
and 0x54 is reserved for the firmware ID (Phase 6 C2).
Plan:
- Firmware (vial-qmk core): a uint8 step counter per knob and direction, bumped in `encoder_handle_queue`,
  and a new VialRGB GET 0x55 that returns them with a marker byte, so the app can tell older firmware
  (which echoes the request).
- App (matrix tester): poll 0x55 with the matrix; when a counter moves, light that knob's ↺/↻ widget and
  play the "ok" sound. The option does not appear on firmware without 0x55.
- Works only on boards flashed with the release that carries it (v5.11 or later).
