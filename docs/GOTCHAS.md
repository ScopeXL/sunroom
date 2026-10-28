# Gotchas, by area

Things that cost time once: the symptom, the cause, and the fix. `CLAUDE.md` keeps the ones any
task can hit (tooling, migrations, plugins, tests in general, motion); these belong to one screen
or one widget. Add a line where it fits, and move lines here from `CLAUDE.md` when it nears its
size limit.

## The wall's keyboard, sheets and panels

- A tap on a wall-screen button missed: the field lost focus, the keyboard lowered, and the page
  moved under the finger. The keyboard's padding (`--osk-h`) outlasts it by 400 ms.
- A sticky Save bar in the wall's side panel covered the chips above the keyboard: a sticky box
  stops at its scroller's padding, which already holds `--osk-h`. Stick it at `bottom-0`.
- The wall's keyboard couldn't type into a sheet: a modal `<dialog>` makes the rest inert.
  `ui/Keyboard` mounts in the open dialog; a backdrop tap closes a sheet only if the press began
  there (the sheet rises with the keys, so a release can land on the backdrop).
- A wall password field offered capitals: the keyboard's layout comes from TextField's `layout`,
  not `type`. Pass `layout="password"`, and `autoCapitalize="none"` for addresses.
- The wall stayed shifted up after typing: an `overflow: hidden` box still scrolls from script
  (focus, `scrollIntoView`) once its content overflows. The shell is `overflow: clip`.
- A field in the wall's side panel jumped to the top when the keyboard rose: the panel's scroll
  padding already holds the keyboard, and the field's own scroll margin counted it twice.
  `[data-panel] [data-osk]` gets a 1rem margin.
- The Add panel opened scrolled down: a side panel kept the last form's scroll. `ui/SidePanel`
  puts `scrollTop` back to 0 when it opens or its title changes.
- A sliver of the form showed under a pinned button: `ui/PanelActions` has a cover strip
  (`after:`) below itself.

## Components and their tests

- A `createLink` component lost its styles: the router passes its own `className`. Merge it
  after the spread (`shell/HeaderLinks`, `ui/ListRow`).
- The design rules failed on a component's `title="…"` that wasn't a heading: every `title=`
  literal on a component counts as a title, in Title Case. Name such a prop otherwise (`lead`).
- A test couldn't find a switch by its label: `ui/Switch`'s `<label>` wraps the hint too, so the
  name is both. Match the start: `{ name: /^Nightly backups/ }`.
- Two buttons named Close in one sheet: `ui/Sheet` has its own ✕, named Close. Take the last one
  (`getAllByRole(…).at(-1)`; Playwright's `.last()`).
- `react-hooks/set-state-in-effect` refused resetting a sheet when its input changed: reset during
  render instead (`const [shown, setShown] = useState(file); if (file !== shown) …`), as
  `EraseSheet` and `RestoreSheet` do.
- A swipe on a phone's list of lists did nothing in Chromium, while an item's row swiped: the
  row is a link, and a link (or an image) starts the browser's own drag-and-drop. `ui/SwipeRow`
  cancels `dragstart` inside itself.
- A swiped row's red Remove showed as a hairline round every row at rest: its edges sat under
  the row's at fractional pixels. `ui/SwipeRow` draws it only while the row is off its rest.
- On a phone with a PIN set, `asParent` waits for ever on a parent-only refusal: the PIN pad is
  mounted only in the display shell. Offer a parent-only action on a phone only with a parent's
  rights (`session.is_parent`), as the swipes do.

## Backup, restore and the service worker

- `/photos` gave a fresh browser a JSON 404 while e2e passed: the service worker answered
  navigations from its precached `index.html`. Since ADR 0034 it asks the server first (the copy
  answers only offline), but still test routes on a page never loaded before.
- A restart's reload threw "e is not a function": `.then(refresh)` handed the waiter's `true`
  to `reloadFresh` as its optional `reload`. Call through a closure (`.then(() => refresh())`)
  when the function has optional parameters; a test's `vi.fn()` takes anything, so check
  `toHaveBeenCalledWith()`.
- Workbox's `PrecacheFallbackPlugin` failed `exactOptionalPropertyTypes` (its `handlerDidError`
  is `T | undefined`): `{ handlerDidError: () => matchPrecache("/index.html") }` is the same call.
- A refresh behind a proxy could show the proxy's 502 while the container restarts: `NetworkOnly`
  returns any answer. `sw.ts` turns a 5xx into no answer, so the saved page opens.
- A paired wall reloaded while the server was down came back as Pair This Screen: its session
  request gave up after two tries. `DisplayEntry` retries it until the server answers anything
  but a 4xx.
- A backup e2e listed other tests' copies: `/api/_test/reset` left `backups/` alone. Since
  0.12.0 it clears every copy and what the service remembers.
- `DELETE /api/admin/backups/{name}` with an encoded slash in the name got 405, not 404: the
  decoded path matches only the page's GET fallback. Nothing is removed; the test takes either.

## Backend and its tests

- An in-app restart can't `exec` under `uvicorn --reload`: the worker is a spawned child with
  multiprocessing's argv. The dev server writes a watched file instead (`devserver.reload`).
- ruff's ASYNC240 flags a `Path` method in any async function, tests included: `await
  asyncio.to_thread(path.unlink, missing_ok=True)`.
- Patching `module.shutil.disk_usage` patches `shutil` itself for the whole test: patch
  `shutil.disk_usage` and know that's what it is.
- A Protocol over SQLAlchemy `Mapped[...]` fields didn't satisfy pyright: pass a small dataclass
  (`calendar.people.Person`).
- A home server never passed the guard with the tick alone: the guard wants the tick and an
  allowlist row, and nothing wrote the row. `ctx.network.allow` writes it before the first
  check, and a failed check takes it back.
- Test photos that had to differ were taken for one: flat JPEG colors a step apart encode alike,
  and the store dedupes by the bytes' hash. Make such pictures PNG.
- A plugin's spawned task, or a job, that raises stops the whole plugin (`PluginRunner._fail`).
  Work that may fail on its own (a photo library's pass) catches its errors and records them.
- A test's "done on its day" was done late: a completion's day is the household day the clock
  says when it's made, whatever its due date. Set the clock to that day before completing.
- `just db-revision`'s autogenerate wrote the app's own column type
  (`sunroom.db.types.UTCDateTime()`) into the migration, which must not lean on app code that can
  change. Write `sa.DateTime()`, as every migration does.
- `boot.reexec` runs `sys.orig_argv[1:]` again with `sys.executable`: for the console script
  that's `[python, …/bin/sunroom, serve, …]`, for `-m` it's `[python, -m, sunroom, serve]`.
- After the repo's folder was renamed, `uv run pytest` said "Failed to spawn: pytest": a venv's
  scripts keep the old folder's absolute path in their `#!` lines. `uv sync --locked --reinstall`
  in `backend/` and in `kiosk/agent/` writes them again.

## Layout and CSS

- A backdrop under the header's menus covered only the header: the header is a size container
  (`@container`), and a container contains `fixed` boxes. `ui/Menu` closes on a press outside
  and swallows that click instead.
- The rail's fold never eased: `:root[data-motion-ready] [data-surface]` reset `transition` on
  every surface a moment after first paint, and out-ranked the rail's own rule. That rule is
  gone (0.10.0); a theme switch's (`data-theme-switching`) out-ranks every element's own for
  its 600 ms, so a fold during a theme change snaps.
- A fade that only Light showed, on a refresh: the theme arrived with `/api/settings`, after
  the fades were armed, and the page had painted the browser's own dark. `public/theme-boot.js`
  paints the remembered theme first, and the fades wait for the household's (ADR 0032).
- The header was 9 px taller in Tasks than elsewhere: a bordered `Segmented` is 12 px taller
  than a button. As one row the header pads 4 px, and `--header-h` follows `--tap`.

- A select stayed 27 px tall in Safari: WebKit ignores `min-height` on a native select. Use
  `ui/Select` (appearance reset, its own chevron).
- Hours' day columns stopped lining up: `container-type` adds layout containment, and a contained
  box can't be a subgrid. The head and body are the containers, not the column.
- An Hours chip's block sat mid-button: a `<button>` centres its content vertically. Make it
  `flex flex-col`.
- A stacked `Segmented` row rested 4 px scrolled: its snap points sat inside its padding. It
  has `scroll-px-1`.
- At Small text, 8 px gaps became 7 and failed the tap check: rem shrinks. `--spacing-2` is
  `max(0.5rem, 8px)`; Hours chips size by `tapPx(rem)`.
- The now line painted over the Hours day heads when zoomed: a day's body had no stacking
  context, so the line's z-30 beat the sticky head's z-20. The body is `isolate`.
- The Hours grid's scrollbar flickered once a minute on the wall screen: Chromium's overlay
  bar shows on every scroll, and a resting grid sets `scrollTop` each minute to follow now. That
  scroller is `scrollbar-width: none`.
- `motion` still fades under Reduce Motion, and an endless CSS animation at 0.01 ms flickers:
  leave `exit` out (`useMotionReduced`), and give the loop `animation: none`.
- A task row's chevron broke its title mid-word ("Em pty") in portrait's People view, whose five
  columns leave a row about 192 px. The row is a container, and under 13rem the chevron goes.

## Sunroom Screen (the agent beside a wall's browser)

- The screen's own build failed on `virtual:pwa-register`: it reached `ui/StatusLayer` for the
  toasts, which registers the service worker. The toasts are `ui/ToastRegion` now.
- The screen's pages called nothing in Vitest: a client with base `""` makes a relative
  `Request`, which Node refuses (a browser resolves it). The own agent's base is the page's
  origin, written out.
- A card's `getByRole("region")` found nothing: a `<section>` is a region only once it has a name.
  Give it `aria-labelledby` its heading.
- The wall's calls to the agent were blocked by CSP: `connect-src` is widened only for a
  `/display` document that names the port, so the launcher passes `?screen=` on every load,
  nothing remembers it, and a fresh reload goes back to the launcher's address (the rooms
  change the URL and drop the parameter).
- `install.sh` must run on macOS's `/bin/bash` 3.2 (its `--dry-run` in CI, and the Mac's
  install): there an empty array's `"${a[@]}"` is an unbound variable under `set -u`, and
  `${var,,}` doesn't parse. Write `${a[@]+"${a[@]}"}` (or `${a[*]-}`) and `lower`; try it with
  `/bin/bash kiosk/install.sh --dry-run`.
- A read of a missing file printed its error despite `2>/dev/null`: in `tr </missing 2>/dev/null`
  the `<` fails before the later redirection applies. Wrap it: `{ tr </missing; } 2>/dev/null`.
- Google Chrome copied out of its disk image failed `codesign --strict` ("resource fork, Finder
  information, or similar detritus not allowed"): the image's HFS+ volume reports empty Finder
  information on every file, and a copy keeps it. `ditto --noextattr --norsrc` copies it clean.
- A test that loaded `install.sh`'s functions with `. <(sed '$d' kiosk/install.sh)` defined
  nothing on macOS: bash 3.2 can't source a process substitution. Write them to a file first.
- Windows' install line failed at once with "Program 'powershell.exe' failed to run: Access is
  denied", and Defender reported a threat: its machine learning stops a PowerShell *started*
  with a command line that downloads a script and runs it (ClickFix's shape), and the line was
  `powershell -ExecutionPolicy Bypass -c "irm … | iex"`. The bare line is typed in the window,
  `install.ps1` starts no PowerShell of its own, and it avoids script-module cmdlets, since a
  window's policy is Restricted (ADR 0041).
- A console window flashed on a Windows wall every 30 s: the agent runs without a console
  (`sunroom-kioskw`), so each console program it starts (`netsh` for the Network row, `taskkill`,
  `uv`) got a window of its own. Every launch passes `platform/base.py`'s `NO_WINDOW`
  (`CREATE_NO_WINDOW`; `apply.py` has its own copy, being standard library only).
- A Windows screen asked to be paired after every restart: Edge's `--kiosk`, with or without
  `--edge-kiosk-type`, is an InPrivate session. Edge runs `--start-fullscreen` on the screen's
  profile instead, and the watchdog keeps it full screen (ADR 0040).
- A pairing made just before a restart was lost on every system: Chromium writes new cookies to
  disk every 30 s, once 512 changes wait, or when closed through DevTools (`Browser.close`). A
  SIGTERM writes nothing new (tried with Chrome 155), nor most likely does a system shutting the
  browser down, and Python's `terminate()` is `TerminateProcess` on Windows. The agent closes with `Browser.close`
  first, and the page asks it to write the cookies right after pairing (ADR 0040).
- A Mac lost a fresh pairing at a restart: uvicorn waits for every open connection before the
  app's shutdown, with no limit by default, and the wall page's event stream never ends, so the
  agent never closed its browser before launchd killed both. `app.AgentServer` ends the streams
  when asked to stop.
- Chromium's headless profile on a Mac asks the login keychain for its cookie key: a test that
  starts real Chrome passes `--use-mock-keychain`, or a keychain prompt shows on the desktop.
- A screen showed its pairing code twice right after a Sunroom was chosen (code A, then B): the
  page opened Sunroom as soon as it heard the new state, and the agent then restarted the browser
  on it too. The page moves itself; the agent only navigates (DevTools) where no page chose, and
  its policy no longer names the Sunroom, so nothing needs a restart (ADR 0042).

## The board

- A plugin's setting reached the wall minutes late: `plugins.changed` refreshed only the plugin
  list. A new plugin adds its query keys to `PLUGIN_KEYS` (`lib/eventRouter`).
- People's arrows did nothing (0.13.0): they stepped `weekOffset`, which that view never read,
  and the page turn still slid the columns. Every view's arrows must change what that view
  reads, and `BoardControls` names the step by the view ("Next day" on Day and People).

## Time and live updates

- The wall clock ignored the server's time until the next minute: the minute store didn't hear
  about new clock samples. `lib/clock` tells listeners when the offset moves (`onClockMoved`).
- The wall's live icon blinked on every room switch: the kiosk remounts the shell, so the stream
  reconnects. `ui/LiveStatus` shows anything but connected only after 2 s.
- After Erase everything the wall sat on a pair code: its cached setup status said complete.
  `handleSignedOut` invalidates it.

## End-to-end tests

- The test server keeps plugin settings between tests (`/api/_test/reset` leaves
  `plugin_state`): a test that changes one puts it back in `finally`.
- Tap-target checks flagged the page behind an open sheet: a modal `<dialog>` makes the rest
  inert with no `inert` attribute. The check looks only inside `dialog:modal`.
- An a11y check failed only in the evening: the unpaired wall flips from the browser's clock to
  the server's 10 AM, and headless Chromium draws no frame until asked, so 0.01 ms transitions
  held old colors. `settled()` asks for frames; set the server's clock when a test needs "Up next".
- Playwright's `context.route` answers a service worker's own fetches in Chromium (count the hits
  to be sure), so a test can hand the worker a proxy's 502; `setOffline` reaches the worker in
  Chromium, not WebKit.
- "No file links on the wall" can't be `getByRole("link")`: Settings there has its own nineteen
  (the rail, the pages). Look for `a[href^="/api/"]`.

- The wall's keyboard didn't rise in an a11y run: an `Escape` earlier in the test counted as a
  physical keyboard, which keeps the on-screen one down for 5 s. Close things with a tap.
- The tap-target check flagged the buttons under an open menu as its neighbours. It looks only
  inside an open `[role=menu]`'s box, as it does inside a modal dialog.
- A screenshot showed the last shot's zoom: a wall screen remembers its view across a reload
  (ADR 0030). The screenshot spec clears `sunroom.display.*` before every load.
- A render prop that hands out a function touching a ref (`children(close)`) fails the React
  compiler's refs lint. Pass it through a context, or call it only from a handler.

- An e2e helper moved on before sign-in finished on a laptop: the Today panel's "Up next" shows
  beside Who's using this there. Wait for the URL, not a heading that two screens share.
- WebKit screenshot runs report inline-style CSP violations: Playwright's WebKit screenshot code
  injects a `<style>`. Only the screenshot spec turns `cspGuard` off.
- `settled()` hung on the Hours board: the now line glides in a 60 s transition. It ignores
  animations longer than 10 s.
- The update e2e failed only around 3:30 PM: it counted every toast, and the seed's 4 PM
  practice reminds 30 minutes ahead on the real clock. Count the toast the test means, or set
  the server's clock.
- A wait for the board to come back to this week passed at once: the Week board's region is
  named "This Week" on every week. Wait for the header's This week button to be disabled (This
  month on the Month view).
- The portrait layout test (`lays out its rail or bottom bar…`) failed about one run in seven:
  it read the Today band's box, then the header's, and the header had grown 8 px in between. The
  weather arrives after the board, and in portrait (two header rows) its stacked high and low
  make the first row taller. Since 0.11.0 the today block is `min-h-tap`, so the row no longer
  grows; the test still waits for the weather button, which it measures.
- A click just after a dnd-kit drop did nothing: dnd-kit swallows clicks for 50 ms after a drop.
  Tests wait 100 ms.
- A heading locator matched twice in Settings: the Today panel shows beside it. Use `exact`.
- `getByLabel("Address")` also found the home-network switch, whose label wraps its hint ("an
  address like 192.168…"). Label and name locators match parts of words: use `exact`.
- A task's e2e run filtered its spec (`-g`) and missed an older case in it that the change broke
  (People shares the Day view's day, and an earlier step set it). Run the task's whole spec.
- The e2e job on GitHub failed every release from 0.5.0 to 0.9.1, unseen: the two accessibility
  journeys (about forty axe scans each) passed in under 30 s on the Mac and took longer on the
  4-CPU runner, Playwright's default limit. The base is 60 s and they're `test.slow()`; the
  deploy skill now reports the run.
- A test that skipped itself at once ended "Test ended." and showed as flaky on CI: the `guard`
  fixture fired `page.addInitScript` without awaiting it. `watch` awaits it now.
- The update e2e flaked with the new version named on one hello: a later hello naming the
  page's own cancels the refresh. Name it on every hello.
- A scrollbar check passed on the code it was meant to catch: headless Chromium on a Mac draws
  overlay scrollbars (no width), while Linux and CI draw classic ones. Read the computed
  `scrollbar-width` (or `scrollbar-gutter`) as well as the width.
- A header measured on Sep 30 had no high and low beside the weather: the test moved the
  server's clock back after seeding, and the forecast cached at the seed started at the real
  today. Move the clock before `seed()` when a test needs that day's forecast.
- An exiting `AnimatePresence` child stayed tappable, and cleared a shared ref as it left:
  `ui/Leaves` makes it inert (`useIsPresent`); such a ref is set, never nulled.
- A test of what's painted on top passed without the fix: `document.elementFromPoint` skips a
  `pointer-events: none` element such as the now line. Make it hittable for the measurement.
- A role locator's `toHaveCount(0)` passed before a chip had faded: leaving, it's `aria-hidden`
  at once. Poll for what the test means.
- `getByRole("button", { name: "Eggs" })` on a phone also found the swiped row's hidden
  "Remove Eggs": Playwright's role queries don't skip `inert`. `ui/SwipeRow`'s hidden action is
  `aria-hidden` too.
