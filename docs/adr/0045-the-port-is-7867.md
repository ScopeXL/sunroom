# ADR 0045: Sunroom's port is 7867

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

- Sunroom has answered on 8080 since the start, and that's the most crowded port there is: GitHub's
  code search finds about 970,000 public `8080:8080`, and many programs on a home server want it. The
  owner asked for a port of Sunroom's own before 1.0 brings strangers, and then for a full cutover,
  rather than a new number outside the container and the old one inside.
- What a household already has can't be rewritten from here. A hand-edited compose file says
  `8080:8080`, a proxy may point at `sunroom:8080`, and an all-in-one Pi's Sunroom is brought along
  overnight by `/opt/sunroom/update.sh`, which doesn't roll back and which an update doesn't replace.
  With the image listening only on a new port, each of them stops answering at its next pull.

## Decision

- **7867**, which spells SUNR on a phone's keypad. From the survey of 2026-11-03: unassigned at IANA,
  not in nmap's list of ports, not among the ports browsers refuse, below the ranges systems hand out
  for their own connections, and 128 public `7867:7867` on GitHub. (Runner-up 7666, ROOM, is in two
  self-hosted media apps' development setups; 5778, the Sun's temperature, is Jaeger's.)
- **Inside and out:** the Dockerfile's `PORT` and `EXPOSE`, the server's default, the compose example's
  `"7867:7867"`, the Pi's `"@PORT@:7867"`, Sunroom on a computer (7867 or the next free one up to 7886,
  a remembered port staying), the screens' network search (7867, 80, 443), and development.
- **The image also answers on the container's old port,** from the same process: `SUNROOM_OLD_PORT=8080`
  in the Dockerfile and `cli._both_ports`. So compose files, proxies and all-in-one Pis from before
  keep working with nothing to do, and a household moves when it likes (DEPLOY.md, Updating).
  `just smoke-image` checks it. Deleting that one line ends this, and old compose files then stop
  answering, so that release has to say so (V1.md, D23).
- **`cli.py` makes those sockets,** not uvicorn's `Config.bind_socket`, which makes them inheritable:
  `boot.reexec` relies on close-on-exec, or the new process couldn't bind its own port. Away from the
  image there's no old port, and uvicorn binds as it always has.
- **Running the installer again keeps the port it finds** (`existing_port`), so it never moves a saved
  address. The Pi's compose file also says `PORT: "7867"`, because `update.sh` can go back to an older
  image, which listens on its old port unless told.

## Consequences

- A new screen doesn't find a Sunroom still published on 8080 by itself, and its household types the
  address. A 0.18 screen looks on 8080, 80 and 443 until it updates itself.
- Going back to 0.18 or older with a compose file already moved to `"7867:7867"` needs `PORT=7867` set
  or the line put back.
- The root helper's text changes (its avahi fallback), so Pi and Linux screens rewrite it at the update.
  `SYSTEM_PART_SINCE` stays at 0.18.0: a helper from then on can replace itself, so no screen needs the
  terminal for this.
- ADRs, the M plans and old CHANGELOG lines keep 8080 as history until V1's Phase D removes them.
  `SUNROOM_UPDATER_URL` in V1.md names Watchtower's own 8080, not Sunroom's. The website has its own
  copies (`../sunroom-site`), to change the day this is released.
- A `.env` made by `just setup` before this may say `PORT=8080`, which `just dev`'s proxy no longer
  expects: delete that line.
