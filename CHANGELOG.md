# Changelog

Everything that changes in Sunroom, written in plain English. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Sunroom has a Discord. Its link is in Settings → Support Sunroom and in the Settings header
  (a paired screen shows a code to scan).
- A new household starts on the Week view with the Hours layout.
- Settings → Devices renames a paired screen: tap its row.
- This Screen can uninstall Sunroom Screen from the computer it runs on: it asks first, unpairs
  the screen, and, when Sunroom itself runs there, removes it and the family's data too once the
  household password is typed.

### Changed

- The Calendar's views are one button in the header, **View**, which opens a menu with a small
  drawing and a line for each: Week, Rolling Week, Day, Month, People and Today. Rolling Week is
  a view of its own now, in that menu and as a Home view in Settings → Display, instead of a
  switch beside Agenda · Hours.
- This Screen's Rotation turns the picture on Windows and Linux computers too, for a display
  mounted on its side that the computer doesn't know about.
- Shut Down's question says it turns off the computer this screen runs on, and its other button
  is Cancel.
- Every screen installs Sunroom Screen's updates overnight by itself unless Updates is turned off
  in This Screen.
- The Address row says whether Sunroom runs on this computer or on another, and Change Address's
  question has a Cancel button.
- This Screen shows the connection (Wi-Fi and its network, wired, or not connected) and no longer
  offers to open the computer's network settings. A Mac on Wi-Fi now says so, where it said
  "Wired".
- Setup says "You can change all of this later in Settings." instead of promising three minutes,
  and ends on **All Done!** with one line and the Open Sunroom button.
- A screen that has just chosen its Sunroom, or set one up on this computer, no longer closes its
  browser and opens it again: it simply shows Sunroom, once, with one pairing code.
- The screen's first page is one choice: tap **On This Computer** or **Connect to a Sunroom**,
  then Continue. Where Is Your Sunroom? checks an address as soon as you leave the field, says
  Found or Not Found on the button, and offers Use This Sunroom right beside it.
- A new screen is called "Wall screen" until it's named, and Sunroom no longer assumes it hangs
  in a kitchen, nor that everyone else uses a phone: the app, the installers and the docs say
  "the screen" and "your devices".

### Removed

- Sunroom OS, the ready-made card image for a Raspberry Pi, is retired: set a Pi up with the
  one-command installer on Raspberry Pi OS instead (docs/KIOSK.md). The 0.16.1 release keeps the
  last image, and Raspberry Pi Imager's Sunroom entry stops updating.

## [0.16.1] - 2026-10-27

### Changed

- Behind the scenes: the Windows installer no longer starts a second PowerShell, which Microsoft
  Defender could stop too; it downloads uv's own zip and checks it before unpacking it.

### Fixed

- A Windows kitchen screen no longer flashes a black command window every half minute, nor when
  its browser restarts, when it updates, or while it sets Sunroom up on that computer.
- Installing the kitchen screen on Windows no longer gets stopped by Microsoft Defender ("Access
  is denied", and a warning that it found a threat). Type the install line straight into a
  PowerShell window:
  `irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1 | iex`.
- Removing the kitchen screen from Windows no longer suggests a command that doesn't exist; it
  points to the right steps instead.

## [0.16.0] - 2026-10-23

### Added

- The kitchen screen can set Sunroom up by itself: before setup it offers **Set Up Here** beside
  the QR code for a phone, and the first steps (the household password, the people, a parent PIN,
  calendars) run right on the screen, on its keyboard. The screen then becomes the family's
  kitchen screen without a pairing code, and its last page has the QR code phones scan to join.

### Changed

- On a kitchen screen run by Sunroom Screen, Settings opens on **This Screen**: it comes first,
  in a box of its own, and says its settings (the network, updates and power) are for that screen
  only, apart from the family's Sunroom below it.
- Behind the scenes: the install steps for each kind of computer, in the README and the kitchen
  screen's guide, are kept up to date whenever the installer changes.

### Fixed

- A kitchen screen on Windows stays paired when the computer restarts. Microsoft Edge's kiosk
  mode forgot the pairing every time it closed; Edge now runs full screen on the screen's own
  profile, and goes back to full screen by itself if someone leaves it.
- A kitchen screen keeps a pairing made just before a restart, on any computer (a Mac forgot one
  once): the browser now saves the pairing the moment the screen is paired, and Sunroom Screen
  closes the browser properly when it stops.

## [0.15.0] - 2026-10-22

### Added

- Sunroom can run on the kitchen computer itself, on a Linux computer, a Mac with Apple silicon or
  Windows as well as a Pi, with no Docker: choose **On This Computer** on the screen, and Sunroom
  Screen sets it up, starts it with the computer, keeps the computer awake for it and keeps it up
  to date. The family's data stays in a folder for that computer's user, with nightly backups as
  always.
- Behind the scenes: each release on GitHub also carries Sunroom itself, ready to run on a
  computer with the exact versions of everything it was tested with; Sunroom now runs on Windows
  too; and the installers can be tried on another computer before a release.

### Changed

- One command sets up a kitchen screen on a Raspberry Pi, another Linux computer or a Mac, with
  nothing to install first and no options: it installs what the screen needs, a browser too when
  there's none (Chromium, or Google Chrome from Google on Ubuntu and on a Mac), and starts the
  screen, which finds Sunroom on your network. To put Sunroom itself on a Pi as well, add
  `--with-sunroom` (no option used to mean Sunroom and the screen); a Pi that already runs
  Sunroom keeps it when the installer runs again.
- A new screen's first page asks where your family's Sunroom will run: **On This Computer** sets
  Sunroom up right there (Setting Up Sunroom shows how far it is, and why it stopped with Try
  Again), and **On Another Computer** finds the one you already have or takes its address. Each
  says what it is and when to choose it.
- On Windows, options can go on the installer's one line too, and its last line says how to
  remove it with a command that works without a copy of the script.

### Fixed

- A Linux screen that finds its Sunroom by itself no longer asks on the screen to let Sunroom
  reach it: Sunroom Screen keeps the browser's settings in step with the screen's address, as on
  a Pi.
- A Linux computer with Chromium from a snap (Ubuntu's) no longer tries to run the kitchen screen
  in it, where it couldn't open its own settings; it gets Google Chrome instead.

## [0.14.0] - 2026-10-21

### Added

- The Week view's header has a Rolling week switch, so a screen can keep today in the same
  column for itself; Settings → Display → Rolling week still sets every screen.
- Tasks → All Tasks lists every task, due this week or next month, with its rule and its next
  day; tap one to change or remove it.
- Settings → Photos & Screensaver → Photo Libraries: connect an Immich server with its address
  and an API key, and its people, albums and tags appear to pick from, with a sentence that says
  what's shown (every photo, newest first, when nothing is picked). The screensaver draws on them
  within minutes, up to the number you keep; a library's photo says "From Immich" and is hidden
  rather than removed. Immich is the first library, and more kinds can follow.

### Changed

- Every item on a list ends in a small arrow (›), so it's plain that a tap opens it to change
  its day, who it's for, or remove it; on a phone, a row swiped to the left shows Remove, for any
  item, and for a whole list on a parent's phone or its maker's.
- Every task ends in a small arrow (›) too, and a task's sheet says what it is in words; on the
  wall, Change asks for the PIN before its form, and Skip Today shows only when the task is due
  today. On a parent's phone a task row swiped to the left shows Remove.
- A task that's finished (done on its day, or past its last repeat) leaves for Recently Removed
  the next day, where Put Back keeps it; a person whose tasks are all finished no longer keeps an
  empty column.

### Fixed

- On the People view, the arrows go to the day before or after, Today brings it back, and the
  day is written over the columns; a person's tasks on another day show without boxes. The
  Today view no longer shows arrows that did nothing.
- A calendar server or a photo library on the home network can be allowed from its own sheet:
  the "This server is on your home network" tick now does what it says.
- Behind the scenes: a photo library's key never goes along when a server sends Sunroom on to
  another one, and the log never shows it.

## [0.13.0] - 2026-10-21

### Added

- Sunroom Screen, the program that now runs a kitchen screen, sets the screen up in Sunroom's own
  look: it joins Wi-Fi, finds the Sunroom on the home network or checks an address typed on its
  keyboard, and when it can't reach Sunroom it says so, keeps trying, and goes back by itself.
- On such a screen, Settings → This Screen restarts or shuts it down, updates it, changes its
  Wi-Fi, turns it, or points it at a different Sunroom.
- Such a screen can keep its own software up to date overnight (Settings → This Screen →
  Updates), and goes back to the version before if a new one doesn't start.
- A Pi that runs Sunroom announces it on the home network, so screens find it at once.
- The installer can make another Linux computer a kitchen screen, and `--dry-run` shows what it
  would do without changing anything.
- Sunroom OS: a memory card image for a Raspberry Pi that is a kitchen screen from its first
  start, written with Raspberry Pi Imager; no terminal, no installer.
- A screen running Sunroom OS can run Sunroom itself: Run It on This Screen downloads it,
  starts it, and opens its setup for a phone.
- A Windows computer or a Mac can be a kitchen screen too: one line installs Sunroom Screen for
  the person signed in, with no administrator, and it starts at sign-in.
- Behind the scenes: Sunroom Screen's tests run on Linux, macOS and Windows, and each release on
  GitHub carries it, the installers and the Sunroom OS image, with checksums.

### Changed

- The kitchen screen installer no longer needs Sunroom's address: without `--url`, the screen
  finds Sunroom on the home network after the restart, or takes the address on the screen. Run
  the installer again on a Pi set up before to switch it to Sunroom Screen; its pairing is kept.

## [0.12.1] - 2026-10-21

### Changed

- The kitchen screen's keyboard shows letters only; 123 switches to numbers and symbols.

### Fixed

- On the kitchen screen's Hours view, the now line no longer shows over the day names when zoomed
  in.

## [0.12.0] - 2026-10-16

### Added

- Four more colors for people and calendars: Orange, Brown, Gray and Lime.
- Settings → Tasks → Stars gives or takes stars for several children at once, and Custom… picks
  any number from 1 to 100.
- Settings → Support Sunroom: what Sunroom is (free, open source, not for profit), how to support
  it, and Send Feedback, which opens a GitHub issue with the version filled in.
- An event whose title names people in the household is theirs: "Mia & Leo's Skate Lesson" shows
  in Mia's and Leo's columns, on top of its calendar's person, on import and when it's added.
  Set Who by hand and Sunroom stops guessing for that event.
- A chip for several people shows a bar in each of their colors.
- Settings → Calendars & Accounts → Default reminder: events with no reminder of their own remind
  on paired screens this long before.
- When something needs a parent (a calendar that stopped syncing, a photo source that fails, a
  backup that didn't complete or is a week old, a feature that stopped, a full disk), a Needs
  Attention icon shows at the top of every room on the wall and on a phone's Today; a tap lists
  what's wrong and opens the settings that fix it. The pill above the days is gone.
- Settings → Backup: Nightly backups can be turned off, and you choose how many daily and weekly
  copies to keep; every copy on the server is listed, newest first, to download or remove; one
  Download button offers Data Only (a fresh copy) or Data & Photos.
- Settings → Backup → Restore from a File: choose a copy you downloaded (Data Only, or Data &
  Photos), see what it holds, type the household password, and Sunroom restarts with it; every
  phone signs in again and wall screens show a pair code. The data from before is kept on the
  server as a copy.

### Changed

- Sunroom says "devices" for the phones, tablets and computers signed in with the household
  password, and "paired screens" for the wall. A paired screen no longer shows what it can't do,
  nor lines saying to do it from a phone; two tips say what signed-in devices can do that a
  screen can't.
- Setup asks for a household password of 8 characters or more (it was 12), starts the
  household's name as Home, offers Family as a choice, and lets you pick Light, Dark or Auto
  before you finish. Its words say "devices" and "paired screens".
- About says URL, Updates, "Check for updates daily" and "This is the latest version", and its
  small print credits Open-Meteo for the weather.
- Settings → Household says what the location is for, and that only your city goes to
  Open-Meteo.
- Tips under the board are on for everyone; turn them off in Settings → Display → Show tips.
- The Remind row offers 5, 15 and 30 minutes and 2 hours as well.
- Sunroom works behind any reverse proxy (Tailscale, Caddy, Cloudflare, your own) with nothing to
  set: it believes a proxy on the home network about https and the phone's address, and answers
  to any name. TRUSTED_PROXIES is gone (an old line is ignored, with a note in the log).
  APP_ALLOWED_HOSTS is now an optional lock: set it and Sunroom answers only to those names and
  local ones. About no longer shows the phone's own address.
- Back Up Now sits in the Backups heading; Export says what it is for and is named Export.

### Fixed

- Settings → Display → Return to the calendar after now counts for Settings too: with Never, the
  wall stays where it is (the parent PIN still locks after 2 minutes, and its pad never comes up
  by itself).
- Choosing "The person's color" for an event that had its own color now clears it.
- Picking a person no longer squeezes the ring against their avatar and name on the wall.
- A one-off change the server sends for a synced event keeps the series' people and reminders;
  saving a synced event no longer pins its calendar's person to it, and a synced event set to
  Everyone by hand stays Everyone.
- A reminder now comes back when an event is reopened: the row knows 30 minutes and any other
  value, a change to one occurrence shows on that occurrence, two reminders stay two, and "All
  of Them" reaches the changed occurrences too.
- After an update, refreshing a paired screen or a phone that installed Sunroom shows the new
  version at once. Before, the old page stayed until the screen's 3 AM reload or the browser's
  cache was cleared. Offline, the screen still opens from its saved copy.
- A paired screen that reloads while Sunroom is down waits for it and comes back as itself.
  Before, it could ask to be paired again once Sunroom was back.
- Behind the scenes: `sunroom restore` and Restore from a File share their checks; new tests
  cover the proxies, the copies on the server, restarting after a restore and the people a title
  names; and the next update's upgrade tests start from this version's database.

## [0.11.0] - 2026-10-15

### Added

- Settings → Display → Rolling week: the Week view shows yesterday, today and the five days
  after, so today always sits in the same column. Off, as before, it shows the calendar week.

### Changed

- In the header the date and the time sit on one line, and the weather is a round button with a
  chevron that opens the forecast; the day's high and low moved into the forecast's first line.
- The weather's sheet says Today and Forecast, names your town without its country on one line,
  and opens with what the weather is now and today's high and low.

### Fixed

- On the Hours grid, zoomed in, the scrollbar no longer flickers every minute: there is no
  scrollbar. The hours still scroll under a finger, and Fit the day shows the whole day.
- On a tall screen the header no longer grows when the weather arrives.
- Behind the scenes: new tests check the forecast's sheet, the header's line and that the Hours
  grid draws no scrollbar, and the next update's upgrade tests start from this version's
  database.

## [0.10.0] - 2026-10-14

### Added

- Settings → Calendars & Accounts starts with Default calendar: where new events go, and it can
  be an Apple or Google calendar too. Add starts with it, and you can still pick another there
  (an account's calendars are named after it: Apple · Family). Sunroom always keeps one calendar
  of its own, so the last one can't be removed.

### Changed

- Buttons are written the way titles are: Add Photos, Save Changes, Check Now.
- On the Hours grid the zoom's buttons read Fit the day, Zoom out, Zoom in.
- The Today panel says "Nothing today"; on the People view a clear day reads "Free day".
- In the header the date, the time and the weather line up.
- Coming Up on the Today panel shows birthdays only within a window (a month by default;
  Settings → Features → Countdowns → Birthdays in Coming Up). Countdowns you add always show.
- Settings → Phones & Screens is now Devices: Paired Screens on top, then Phones & Computers,
  each with the right icon (a computer was listed as a phone). Add a Device replaces Add a
  phone.
- An empty room (Lists, Tasks, Photos, Countdowns and the rest) shows an icon, what goes there,
  and one big button to add the first thing.
- Add an account starts with Apple (it said iCloud), then Google, Holidays, Another calendar and
  A calendar server. An iCloud account you already have is called Apple now, and an account's
  sheet lists the calendars that sync first.
- Setup fills a computer's screen: the six steps are listed at the left with the current one
  marked, and each step's form sits beside them. On a phone a progress bar shows how far along
  you are.
- The kitchen screen's keyboard sits centred across the bottom of the screen, with a row of
  numbers above the letters.

### Fixed

- A refresh paints the screen in its theme straight away: the header, the rails, the buttons and
  today's column no longer show another color and fade. Changing the theme crossfades
  everything together.
- A sheet no longer shifts when a toast fades, and a toast no longer jumps into a sheet that
  opens over it.
- On a computer, Settings → Devices (it was Phones & Screens) said to type the kitchen screen's
  code, with nowhere to type it. Pair a Display there now opens a box for the code, on phones
  too.
- Check Now in About found no versions: Sunroom's versions on GitHub are tags, not releases. It
  reads them now.
- Behind the scenes: the checks on GitHub have the time they need and every release reports
  them, a layout test no longer fails now and then, and checks can run one test at a time.

## [0.9.1] - 2026-10-14

### Fixed

- Left alone for two minutes, the kitchen screen went back to the Week with the rail and the
  Today panel open, undoing what you'd picked. Now it only comes back to this week, shows
  everyone's events again and closes what was open. A folded rail, a hidden Today panel, the
  view (Month, Day…), Agenda or Hours and the zoom all stay, and a zoomed Hours grid scrolls
  back to the current time.
- A change in Settings → Display to Home view, Week layout, Today panel or Compact rail shows
  at once, even on a screen that had picked its own. Compact rail's hint now says the rail
  opens back out from the header.

## [0.9.0] - 2026-10-14

### Added

- A kitchen screen comes back to what it was showing after a refresh, an update or a restart:
  the room, the view, who's filtered, the Week layout and zoom, the panel and the rail.
  Settings → Display → When it starts can make it open on the home view instead.

### Changed

- The live-updates icon shows only while the screen is reconnecting, checking every 30 seconds,
  or can't reach Sunroom. Connected, the corner is clear.
- Setup asks for your city and finds it as you type. So does Settings → Household → Location.
- Setup no longer stops to pair the kitchen screen: pair it whenever it shows its code, from
  More → Pair a Display.
- On a paired screen the mouse pointer disappears a few seconds after it stops moving.
- The kitchen screen's header is lighter: today at the left, then the week's arrows (and Agenda
  or Hours on the Week view); at the right a Filter button with the people, the views and the
  Today panel's button. The month's name and the week's dates left it (the days say when they
  are; the Month view says its month). The Hours zoom sits on the grid's corner.
- Rooms the rail already names no longer repeat their name in the header.
- Add is in three parts, What and who, When and Details, with room between them. Time, How
  long and Repeats each show your choice on one button and open their picker under it; the row
  of suggested times is gone.
- A meal is one box: type it, or tap a saved meal under it as you type.
- The Save button stays in view at the bottom of every sheet, and a saved meal's emoji is
  picked from a row (the kitchen screen's keyboard has none).
- Settings' list is wider, so every page's name fits on one line.
- Google's app keys are asked for inside Sign in with Google, where they're used, instead of
  on Features.
- The rail shows the Sunroom mark alone at its top, as tall as the header; Hide the rail moved
  into the header beside the date, across from the Today panel's button; folded, Add is the
  size of a room's icon and the rail eases shut and open instead of jumping.
- Behind the scenes: the upgrade tests start from 0.8.0's database, and the end-to-end tests
  know when a screen hears live updates without looking for the icon.

### Fixed

- In development the city search answers any name (it made up only two).

## [0.8.0] - 2026-10-12

### Added

- Settings → Backup → Erase everything starts Sunroom over, after a backup and your household
  password. Not from the kitchen screen.
- Settings → Display → Text size has a Small choice for screens around 1920×1080. Buttons stay
  finger-sized at every text size.
- Custom repeats for events and tasks: every few days, weeks, months or years, on the days you
  pick, ending never, on a date or after a number of times.
- A week of days to tap and a month to pick from wherever you choose a day, and a time picker
  wherever you choose a time, a task's Due included.
- A task has a start day.
- Hide the rail from the button at its top for a wider board: it folds to its icons, and comes
  back after two minutes, or stays small with Settings → Display → Compact rail.

### Changed

- Things move now, when you do something: an event eases onto the board when it's added or
  moved and fades when it's removed, a finished task or a checked item slides into Done, the
  week slides when you page, counts pop, and the Today panel slides open and shut. Reduce motion
  turns all of it off.
- Chores are now Tasks everywhere you read it, and Who's Doing What is now People.
- Button groups have more room around each word.
- The top of the kitchen screen is one bar: the date, time and weather at the left, the page's
  buttons at the right, and the Today panel's button in every room, Settings included. The
  calendar's views (Week, Day, Month, People) are icons there, with the one you're on written
  out.
- Hours zooms with Zoom in and Zoom out buttons, as far in as you like; Fit the day shows the
  whole day again. They replace 24h · 12h · 1h · 15m.
- Add is laid out for a finger: one row for what you're adding (Event, Item, Task, Meal,
  Countdown), then a form for it with every choice on its own row. Who is always one line, the
  days follow your week (Sunday or Monday first), and the button stays above the keyboard.
- A new task is for Anyone until you pick someone.
- Settings save as you change them. The Save changes buttons are gone; a person's and a
  calendar's sheets still have Save.
- Features is shorter: Tasks, Meals and Photos & Screensaver each show a row that opens their
  own page, and Sign in with Google's keys sit behind a Set up button.
- Meals has a switch for each meal you plan, "Show breakfast on the calendar" and so on, where
  there was one for dinner. If dinner was on your calendar it still is.
- Photos start after 15 minutes by default now; a screen set to 10 minutes starts after 15 until
  you pick another. You can also wait an hour, and change the photo every 5 minutes.
- Shorter words in Settings: Lists' "Clear completed items after" (Never, 1 day, 3 days, 1 week),
  Weather's "Temperature unit" (Auto, °F, °C), and the screen's evening "Brightness" as 60%, 40%
  or 20%. "Return to the calendar after" starts with Never.
- Settings → Display says what Daylight tint does, and Theme's hint mentions 7 PM only until
  your location is set.
- In Settings you tap the row to edit it: a person, a calendar, an account, a reward or a
  routine. The Change buttons beside them are gone.
- An account opens a sheet of its own: Refresh now, a Sync switch for each of its calendars, a
  "Show on" switch for each synced calendar once a screen is paired, and Remove account. A
  synced calendar's name opens whose it is and its color.
- Picking a color shows the ones nobody uses first, and says whose the others are.
- Recently Removed is its own page in Settings, not the end of Household.
- The Sunroom mark sits at the top of the rail, and Settings is a gear now. The padlock shows
  only while a paired screen's Settings are locked behind the PIN.
- Behind the scenes: a feature's settings can change shape in an update without losing what
  you chose, and the upgrade tests start from 0.7.0's database.

### Fixed

- Changing an event that repeats in a way Sunroom's form can't show (from another calendar, say)
  no longer drops its repeat when you save. It shows as "As it is" and stays untouched.
- The Add panel on the kitchen screen opens at its top, with what you can add in view.
- Export everything no longer includes Google's client secret.
- A setting changed on a phone shows on the kitchen screen at once, the screensaver's timing and
  the Tasks board's stars included. They used to wait up to five minutes.
- Turning a feature on or off no longer makes the other rooms blink off the rail.
- A laptop's Backup page has its downloads: Download backup, Download everything and Export
  everything used to show on phones only.

## [0.7.0] - 2026-10-09

### Added

- The week can show each day as hours, midnight to midnight, with longer events taller and the
  now line creeping through today: Settings → Display → Week layout → Hours, or the Hours
  button on the board. When a day is busy, zoom with 24h · 12h · 1h · 15m.
- Tips: Settings → Display → Show tips puts one thing Sunroom can do under the board, a new one
  every half hour.
- The top-right corner of the board, and the phone's Calendar, show whether the screen is
  getting live updates: connected, reconnecting, checking every 30 seconds, or offline. Tap it
  to hear which. Settings → About → Connection shows the same icon.

### Changed

- Titles, headings and the names of rooms, views and tabs now capitalize each word
  ("Calendars & Accounts", "This Week", "Who's Doing What"). Buttons and messages stay as
  they were.
- "Kid" is now "Child" everywhere you read it.
- Adding a person is one row, their name, Parent or Child, and Add, in setup, Settings →
  Family and Who's Using This. Child stays picked for the next one.
- The Today panel's button at the top of the board is now an icon, the same size as the
  arrows beside it.
- Settings → About → Storage says "Free space".
- Add an account works on any device: a phone, a computer, or the kitchen screen, where the
  password is typed on its own keyboard and stays hidden. Google's helper and Sign in with
  Google show a code to finish on a phone. Back from Google's sign-in, Calendars & Accounts
  says how it went and opens the new account's calendars.
- Add photos from a computer's browser too, not only a phone: Photos → Add photos, and a
  person's photo in Settings → Family.
- After you update Sunroom, every kitchen screen and phone that's open says so and refreshes
  itself.
- Behind the scenes: the upgrade tests start from 0.6.0's database, and the test server can act
  as a newer version to check that every screen refreshes.

### Fixed

- Times on every screen now follow the household's time zone and 12- or 24-hour choice from
  Settings → Household, not the device's.
- A person's birthday now shows on the calendar as a chip in their color, with Countdowns on or
  off. Before, it was a grey star that depended on Countdowns.
- Events on the kitchen screen that can't be moved (from a read-only calendar, a dinner, a
  birthday) no longer read as unavailable to a screen reader.
- On a portrait kitchen screen, a busy day's all-day events no longer spill into the next
  day's row or hide its other events: whatever doesn't fit is behind "+N more".
- On the week board, today's now line always shows, even when the day's events don't all fit.
- The kitchen screen's keyboard now types into sheets (changing a person, setting the PIN), and
  the sheet moves up so the field stays above the keys.
- The code in the kitchen screen's Photos room opens Sunroom on a phone that has never used it,
  instead of an error.
- After typing in the Add panel or a sheet, the kitchen screen no longer stays shifted up with
  the clock cut off at the top.
- The Today panel scrolls when it holds more than fits, instead of cutting its last lines.
- At Extra large text, and on a laptop's shorter screen, the rail's rooms make room so Add and
  Settings stay on the screen.
- "Change which?" keeps the days' capitals: "every week on Tue and Thu".
- The Today view waits for the day's events before saying "Nothing on today."
- Settings choices with longer words (Change photo every, Clear done items) wrap as buttons on
  a phone instead of running into each other, and Google's helper asks for its key file with a
  proper Upload the key file button.

## [0.6.0] - 2026-10-08

### Added

- The kitchen screen can dim in the evening before it sleeps: Settings → Display → Dim in the
  evening, from the time you choose, a little, half or low.
- Settings → About → New versions: Sunroom can check once a day whether there's a new version,
  and says how to update. It's off until you turn it on.
- Settings → Backup → Download everything: the family's data and every photo in one file, to
  keep somewhere safe. [docs/RESTORE.md](docs/RESTORE.md) shows how to put it back, on the same
  server or a new one.
- On a Raspberry Pi, the screen itself now switches off at bedtime and turns down in the evening
  (on monitors that allow it), and a tap brings it back. Run the Pi installer again to add this
  to a screen you already have (docs/KIOSK.md).

### Changed

- On an upright kitchen screen, the Today band at the top now fits everything (Tonight and Coming
  up too), in three columns.
- When a chore with stars is done, the "+2" flies to the person's picture on the Today panel.
- A long press on a list's tile opens Change list.
- Adding an iCloud or Google calendar on a phone: each step now has a drawing of what to tap.
- The Copy button for Google's helper address works on a plain home address too (it did
  nothing there before).
- Behind the scenes: restoring a backup checks it completely before anything changes; new guides
  for choosing the hardware, reaching Sunroom away from home, and adding a feature; and the
  privacy page lists everything Sunroom sends and to whom.

## [0.5.0] - 2026-10-08

### Added

- Meals: the week's dinners on the kitchen screen and on phones.
  - Tonight's dinner, and who cooks, shows on the Today panel.
  - Every meal you add is kept under Saved meals, so next week it's one tap. A saved meal can
    have its recipe link and ingredients.
  - Add ingredients to Groceries puts a meal's ingredients on your grocery list in one tap.
  - Swap days, and Copy last week, both with Undo.
  - Breakfast, lunch and snacks too if you want them, and dinner on the calendar, in
    Settings → Meals.
- Countdowns: "12 days" to the things your family looks forward to.
  - Birthdays count down by themselves, from the birthdays in Family.
  - The nearest three show on the Today panel; on the day it says "Today: Mia's birthday!" and
    the kitchen screen celebrates the first time someone touches it.
  - Add a countdown from any event on the calendar.
  - Keep one off the kitchen screen, for a surprise.
- Photos and the screensaver: add photos from a phone (several at once, iPhone photos too), and
  when nobody has touched the kitchen screen for a while they fade in with the clock and what's
  next. A tap takes you back to where you were.
  - The Photos room shows them all; hide one from the screensaver right there.
  - A parent can start the screensaver from their phone.
  - Photos put in the photos/inbox folder on the server are added by themselves.
  - Settings → Photos & screensaver sets when it starts and how often the photo changes.
- Weather by the clock, with each day's sky on the board and the forecast a tap away, from
  Open-Meteo.
- Where's home: a new first-run step (also in Settings → Household → Location) for the weather.
  With it, the kitchen screen turns dark at your sunset and light at sunrise, instead of 7 PM
  and 7 AM, and it waits until nobody's touching the screen.
- At night, the dim clock shows tomorrow's first event under it.

### Changed

- Behind the scenes: adding photos no longer holds up everything else while they're
  processed, which matters on a Raspberry Pi.

## [0.4.0] - 2026-10-08

### Added

- Lists, on the kitchen screen and on phones: groceries, to-dos, packing lists and your own.
  - Add several things at once ("milk, eggs, bread"), or tap one of the list's Usuals, the
    things your family adds most.
  - Give a thing a person or a day; things due today show on the Today panel under To do.
  - Checking one off strikes it through in the color of whoever checked it, and it moves to
    Done. Clear done tidies the list, with Undo.
- Chores, with a column for each person and one for anyone:
  - a chore can be each person's own, taken in turns ("Mia's turn"), or anyone's ("Who did
    it?");
  - ticking one stamps it, with a burst in that person's color; their last one of the day
    says "All done, Mia!";
  - This week shows how each person did, day by day.
- Stars: chores can give stars, kids see their balance, a week's total and how many days in a
  row they finished everything.
- Rewards: kids ask for a reward with their stars, and a parent says yes or not now, on a
  phone or on the kitchen screen with the PIN.
- Routines: a morning or bedtime checklist a kid runs on the kitchen screen, one big step at a
  time, with a picture for each, ending with a celebration (and stars, if you like).
- Settings → Chores turns stars, rewards, routines and a parent's check on or off, and sets
  up rewards and routines. Turning on "A parent checks finished chores" holds a kid's stars
  until a parent says it's done.
- Who's doing what shows each person's chores under their events, and the Today panel shows
  how everyone is doing.
- Recently removed now brings back lists, things on them and chores, too.

### Fixed

- A calendar address that stops working, say after you reset Google's secret address, now says
  so on the board, and Connect again takes its new address. Before, it quietly kept showing the
  last events it had.
- Behind the scenes: a feature whose background work trips up keeps working on screen, and a
  safety check that each feature switches fully off works again.

## [0.3.0] - 2026-10-08

### Added

- Bring in the calendars you already use, from Settings → Calendars & accounts on a phone:
  - Google, three ways: paste its secret address (shows events only), share your calendars with
    a Sunroom helper you make once, or sign in with Google when Sunroom has an https:// address;
  - iCloud, with an app-specific password;
  - other calendar servers such as Nextcloud and Fastmail;
  - any calendar address (.ics): school, team and Outlook calendars;
  - public holidays for your country and region, with no address at all.
- Each calendar can belong to a person, so its events show in their color, or to everyone, with
  a color of its own (each color says who already uses it). Any calendar can stay off the
  kitchen screen and show only on phones.
- Calendars from iCloud, Google's helper or sign-in, and calendar servers sync both ways:
  - what you add, change, move or remove on the kitchen screen or a phone goes back within a
    minute;
  - changes made elsewhere arrive within about five minutes, or straight away with Refresh now;
  - a change waiting to go out says "Not synced yet".
- An event's sheet says where it comes from, like "iCloud · Work". Events from calendars that
  only show events, such as holidays or a school's calendar address, say so and can't be changed
  by mistake.
- When an account stops answering, the board shows one quiet line ("iCloud hasn't answered since
  9:10 AM. Showing what we had."), and its events stay. A refused password asks to be connected
  again.
- Setting up Sunroom now offers to bring in your calendars just before it finishes.
- Behind the scenes: Sunroom talks to calendar servers through its own guarded connection.
  Passwords, keys and calendar addresses are stored encrypted, and are never shown again or sent
  to another server.

## [0.2.0] - 2026-10-08

### Added

- The calendar. Add an event by typing it the way you'd say it, like "Dentist Thu 2:30pm Mia":
  Sunroom works out the day, the time, how long, who and how often it repeats, and shows what it
  understood as buttons you can tap to fix.
- Events can repeat: every day, on weekdays, every week or two, every month, every year, or a
  pattern of your own. Changing or removing one asks whether you mean just this one, this one and
  the ones after, or all of them.
- The kitchen screen shows the week, one day, the month, "Who's doing what" (a column for each
  person) or a big Today view. Settings → Display → Home view picks which one it comes back to.
- Press and hold an event on the kitchen screen to drag it to another day.
- Everything you add, change, move or remove says so with an Undo button. Removed events stay in
  Settings → Household → Recently removed for 7 days, with Put back.
- The Today panel shows what's on now, what's next and the rest of today, and tomorrow after
  6 PM.
- An event can show a reminder on the kitchen screen 10 minutes, an hour or a day before.
- Tap people's pictures at the top of the calendar to see only their events (and everyone's).
- Today's events that are over fade, so what's next stands out (Settings → Display).
- On a phone, Today shows what's on now and next, and Calendar has Week, Day, Agenda and Month
  views, a search by title or place, and the same editor.
- Settings → Calendars & accounts: calendars of your own, each with a color, whose it is and
  whether it shows on the kitchen screen, and which one new events go to.
- With kid-safe editing on, changing or removing an event on the kitchen screen asks for the
  parent PIN. Adding and moving events don't.
- Behind the scenes: a recurrence engine of Sunroom's own, checked against two reference
  libraries, and the calendar's tables, which the update adds to the database on its first
  start.

### Changed

- The instructions for running Sunroom on a server now start from a `docker-compose.yml` in a
  folder of its own, started with `docker compose up -d` (a Portainer stack still works). They
  also cover running it next to another app that already uses port 8080, and using a host folder
  instead of the `sunroom_data` volume.

## [0.1.0] - 2026-10-08

### Added

- Set Sunroom up from a phone: a household password, the household's name, time zone and first
  day of the week, the people who live here (parents and kids, each with a color), an optional
  parent PIN, and the kitchen screen.
- Pair the kitchen screen by typing the six-character code it shows into a phone, or by typing
  the household password on the screen's own keyboard. It stays signed in, through restarts and
  power cuts.
- The kitchen screen shows this week: the clock and date, today's column lit, a line for now, and
  the Today panel. Turned on its side, Today sits on top and the rooms along the bottom. Two
  minutes after the last touch it goes back to this week.
- Settings on the kitchen screen ask for the parent PIN. Lock closes them, and they lock
  themselves after two minutes.
- Settings: Family (people, the parent PIN, kid-safe editing), Features, Display (theme, text
  size, daylight tint, reduce motion, which side the rail sits, the Today panel, the sleep
  schedule), Household (name, time zone, first day of the week, 12- or 24-hour time), Phones &
  screens (add a phone with a code, mark a kid's phone, sign out a phone, unpair a screen),
  Backup and About.
- The screen sleeps on a schedule, with a dim clock or a black screen, and a tap wakes it.
- Phones get Today, Calendar and More; a laptop gets the kitchen screen's layout and uses its own
  keyboard.
- A change on one phone or screen shows on all of them at once.
- Sunroom installs on an iPhone or Android home screen like an app.
- One Docker container with a data volume, nightly backups, a full export, and `sunroom`
  commands to back up, restore, reset the password and check the setup.
- A Raspberry Pi installer for the kitchen screen, which can also point at a Sunroom running on
  another computer.

### Behind the scenes

- Every change is checked on the kitchen screen's sizes, phones and a laptop, for accessibility
  in light and dark, and for anything private before it can be published; each release is
  started from a clean copy and tried out before anyone can download it.

### Security

- Sunroom answers only to addresses it recognises (local names and addresses, plus the ones in
  `APP_ALLOWED_HOSTS`), refuses changes from other sites, and limits what its pages may load.
- Outside addresses are checked before every connection, so a setting can't reach into your home
  network unless you allow it.

[0.1.0]: https://github.com/ScopeXL/sunroom/releases/tag/v0.1.0

[0.2.0]: https://github.com/ScopeXL/sunroom/compare/v0.1.0...v0.2.0

[0.3.0]: https://github.com/ScopeXL/sunroom/compare/v0.2.0...v0.3.0

[0.4.0]: https://github.com/ScopeXL/sunroom/compare/v0.3.0...v0.4.0

[0.5.0]: https://github.com/ScopeXL/sunroom/compare/v0.4.0...v0.5.0

[0.6.0]: https://github.com/ScopeXL/sunroom/compare/v0.5.0...v0.6.0

[0.7.0]: https://github.com/ScopeXL/sunroom/compare/v0.6.0...v0.7.0

[0.8.0]: https://github.com/ScopeXL/sunroom/compare/v0.7.0...v0.8.0

[0.9.0]: https://github.com/ScopeXL/sunroom/compare/v0.8.0...v0.9.0

[0.9.1]: https://github.com/ScopeXL/sunroom/compare/v0.9.0...v0.9.1

[0.10.0]: https://github.com/ScopeXL/sunroom/compare/v0.9.1...v0.10.0

[0.11.0]: https://github.com/ScopeXL/sunroom/compare/v0.10.0...v0.11.0

[0.12.0]: https://github.com/ScopeXL/sunroom/compare/v0.11.0...v0.12.0

[0.12.1]: https://github.com/ScopeXL/sunroom/compare/v0.12.0...v0.12.1

[0.13.0]: https://github.com/ScopeXL/sunroom/compare/v0.12.1...v0.13.0

[0.14.0]: https://github.com/ScopeXL/sunroom/compare/v0.13.0...v0.14.0

[0.15.0]: https://github.com/ScopeXL/sunroom/compare/v0.14.0...v0.15.0

[0.16.0]: https://github.com/ScopeXL/sunroom/compare/v0.15.0...v0.16.0

[Unreleased]: https://github.com/ScopeXL/sunroom/compare/v0.16.1...HEAD
[0.16.1]: https://github.com/ScopeXL/sunroom/compare/v0.16.0...v0.16.1
