# ADR 0045: Sunroom's port is 7867

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

- Through 0.18.1 Sunroom answered on 8080, the most crowded port there is: GitHub's code search finds
  about 970,000 public `8080:8080`, and many programs on a home server want it. The owner asked for a
  port of Sunroom's own before 1.0 brings strangers, and for a full cutover, rather than a new number
  outside the container and the old one inside.
- Nobody else runs Sunroom yet (the owner, 2026-11-03), so the only install that has to get through the
  change is the owner's own server, whose compose file is edited by hand.

## Decision

- **7867**, which spells SUNR on a phone's keypad. From the survey of 2026-11-03: unassigned at IANA,
  not in nmap's list of ports, not among the ports browsers refuse, below the ranges systems hand out
  for their own connections, and 128 public `7867:7867` on GitHub. (Runner-up 7666, ROOM, is in two
  self-hosted media apps' development setups; 5778, the Sun's temperature, is Jaeger's.)
- **Inside and out, a clean cut:** the Dockerfile's `PORT` and `EXPOSE`, the server's default, the
  compose example's `"7867:7867"`, the Pi's `"@PORT@:7867"`, Sunroom on a computer (7867 or the next free
  one up to 7886), the screens' network search (7867, 80, 443), development, and every doc. Nothing
  answers on the old port any more.
- **Running the installer again keeps the port it finds** (`existing_port`), so it never moves a saved
  address. A Sunroom on a computer keeps its remembered port the same way.

## Consequences

- An install from before has to change at the update that brings this: the `ports:` line to
  `"7867:7867"`, a proxy's target, and the address on devices and screens (a phone's installed app is
  added again, because the port is part of its address). The deploy's report for that release says so.
- A 0.18 screen looks on its old ports until it updates itself; meanwhile it takes a typed address.
- Going back to 0.18 or older needs the old `ports:` line back too, because those images listen on the
  old port.
- The root helper's text changes (its avahi fallback), so Pi and Linux screens rewrite it at the update.
  `SYSTEM_PART_SINCE` stays at 0.18.0: a helper from then on can replace itself, so no screen needs the
  terminal for this.
- `SUNROOM_UPDATER_URL` in V1.md names Watchtower's own port, which isn't Sunroom's and stays. The
  website has its own copies (`../sunroom-site`), to change the day this is released. A `.env` made by
  `just setup` before this sets the old `PORT`, which `just dev`'s proxy no longer expects: delete that
  line.

## Considered

- **The image answering on both ports for a while,** so old compose files needed nothing. It was built
  and tested, then dropped because nobody needs it. If a port ever moves again: uvicorn's
  `Server.run(sockets=[…])` serves both from one process, and the sockets have to be made by hand,
  because `Config.bind_socket` makes them inheritable and `boot.reexec` relies on close-on-exec (with
  inheritable ones the restarted process failed with "Address already in use").
