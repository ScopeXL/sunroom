# Security

## Reporting a problem

Please report security issues privately through GitHub: open the repository's **Security** tab
and choose **Report a vulnerability**. Don't open a public issue for anything that could put a
household's data at risk.

## Supported versions

Only the latest release is supported. Each installation is run by the household that deploys it,
so fixes reach a household when it pulls the new image (or runs `sudo /opt/sunroom/update.sh` on
a Pi).

## How Sunroom protects a household

- One household password, stored as a scrypt hash (or set in the server's environment);
  sign-in and PIN attempts are rate-limited.
- Signed, HttpOnly, SameSite session cookies per device, which can be signed out from Settings.
  A parent PIN guards Settings and changes on the shared wall screen.
- Sunroom believes a reverse proxy's forwarded headers only when the connection comes from the
  home network (loopback, private, link-local and Tailscale addresses), never from the internet.
  `APP_ALLOWED_HOSTS` can lock it to the names you choose, so a web page that points its own
  name at your home address is refused.
- A strict Content Security Policy with a per-page nonce, a CSRF header check and an Origin check
  on every change.
- Outside addresses are resolved and checked before every connection, so a setting can't reach
  into the home network unless the household allows that address.
- Secrets for connected accounts are encrypted at rest with a key kept in the environment or on
  the data volume.
- The container runs as a non-root user with a read-only filesystem apart from `/data`.
