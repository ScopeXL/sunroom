#!/usr/bin/env bash
# Sunroom installer: a Sunroom screen on a Raspberry Pi (Raspberry Pi OS 64-bit,
# Bookworm or Trixie), another Linux computer with a desktop or a Mac, and on a Pi, Sunroom
# itself too. See docs/PLAN.md §13, docs/KIOSK.md and ADR 0037. (Windows has its own,
# install.ps1.)
#
# With no option it sets up the screen, which finds Sunroom on the network by itself.
# On a Pi, three ways to use it:
#   a. only the screen; Sunroom runs on another computer (no option) [--url URL]
#   b. Sunroom and the screen, both on this Pi          --with-sunroom
#   c. only Sunroom, no screen (Raspberry Pi OS Lite)            --server-only
# A Pi set up as b or c stays that way when the installer runs again with no option. Another
# Linux computer or a Mac is always a. Whatever the screen needs is installed, the browser too:
# on Linux the system's Chromium, or Google Chrome where that's a snap (Ubuntu); on a Mac,
# Google Chrome.
#
#   curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash -s -- --with-sunroom
#
# The screen is Sunroom Screen, a program installed with uv from this version's GitHub
# Release (its wheel checked against the Release's SHA256SUMS first), which runs the browser,
# the screen's sleep and brightness and its own pages (docs/M7.md).
#
# Run it as your normal user, not root; it uses sudo where it must. Running it again is
# safe: packages and Docker are installed only when missing, the files it owns are
# rewritten with the same content, and its edits to shared files sit between marker lines
# or are recorded (~/.local/state/sunroom-kiosk/install-state) so kiosk/uninstall.sh can
# take them back. Everything it prints is also logged to
# ~/.local/state/sunroom-kiosk/install.log.
#
# The rest of the kiosk/ folder (files/, labwc-rule.py, update.sh, uninstall.sh) is taken from
# next to this script when present, otherwise downloaded from GitHub at this installer's own
# release tag, so the files and Sunroom Screen always come from one release.
#
# bash 3.2 (macOS's own) must run it: no associative arrays, no ${var,,}, and an array that may
# be empty is expanded as ${a[@]+"${a[@]}"}.
#
# Nothing runs until `main "$@"` on the very last line, so a download that stops halfway
# never runs half a script.

set -euo pipefail
set -o errtrace

KIOSK_VERSION="0.17.0" # Sunroom's VERSION (`just bump` sets it), written into every file it creates
SUNROOM_REPO="ScopeXL/sunroom"
SUNROOM_IMAGE="scopexl/sunroom"
UV_VERSION="0.12.23" # the uv installer it fetches when uv is missing (astral.sh/uv/<version>)
# Google Chrome, when a computer has no browser the screen can use (Google's own downloads).
CHROME_LINUX_BASE="https://dl.google.com/linux/direct"
CHROME_MAC_DMG="https://dl.google.com/chrome/mac/universal/stable/GGRO/googlechrome.dmg"
# Google's Developer ID: the Mac's copy of Chrome must be signed by it before it's installed.
CHROME_MAC_REQUIREMENT='anchor apple generic and certificate leaf[subject.OU] = "EQHXZ8M8AV"'
# Typed in a PowerShell window, never wrapped in `powershell -c`, which Defender stops (ADR 0041).
WINDOWS_COMMAND="irm https://raw.githubusercontent.com/$SUNROOM_REPO/main/kiosk/install.ps1 | iex"

SCRIPT_PATH="${BASH_SOURCE[0]:-}" # empty when the script is piped into bash

STATE_DIR="$HOME/.local/state/sunroom-kiosk"
LOG_FILE="$STATE_DIR/install.log"
STATE_FILE="$STATE_DIR/install-state"
CONFIG_DIR="$HOME/.config/sunroom-kiosk"
SHARE_DIR="$HOME/.local/share/sunroom-kiosk"
WHEELS_DIR="$SHARE_DIR/wheels" # the running agent's wheel and the one before, for updates
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
LABWC_DIR="$HOME/.config/labwc"
XDG_AUTOSTART_FILE="$HOME/.config/autostart/sunroom-kiosk.desktop"
# A Mac starts Sunroom Screen from a LaunchAgent (the label is the updater's too).
LAUNCH_AGENT_LABEL="app.sunroom.kiosk"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"
SERVER_DIR="/opt/sunroom"
# NetworkManager merges conf.d files in byte order and the last one wins, hence "zz-".
NM_DROPIN="/etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf"
# Announces Sunroom on the network for Sunroom screens (ADR 0035); avahi reloads it by itself.
AVAHI_SERVICE="/etc/avahi/services/sunroom.service"
# The screen helper's brightness: the backlight's bl_power for the video group (Raspberry Pi
# OS's own 60-backlight.rules covers brightness only), and i2c-dev at every start for DDC/CI.
BACKLIGHT_RULE="/etc/udev/rules.d/90-sunroom-kiosk-backlight.rules"
I2C_MODULES_FILE="/etc/modules-load.d/sunroom-kiosk-i2c.conf"
# Sunroom Screen's few root tasks on a Pi (the browser's policy, updates), and who may run them.
ROOT_HELPER="/usr/local/sbin/sunroom-kiosk-root"
SUDOERS_FILE="/etc/sudoers.d/sunroom-kiosk"
BLOCK_BEGIN="# >>> sunroom-kiosk"
BLOCK_END="# <<< sunroom-kiosk <<<"
HEALTH_TIMEOUT=300

# Options
MODE="display" # display | all | server
WANT_DISPLAY_ONLY=0
WANT_WITH_SUNROOM=0
WANT_SERVER_ONLY=0
KEPT_MODE=0 # a Pi that runs Sunroom from an earlier install keeps it (no option given)
URL=""
VERSION=""
PORT=8080
PORT_GIVEN=0
OUTPUT=""
OUTPUT_GIVEN=0
ROTATE=0
BRIGHTNESS="auto"
FORCE_HDMI=""
SCREEN_HELPER="yes"
SCREEN_OPTIONS_GIVEN=0
NO_REBOOT=0
FORCE_X11=0
DRY_RUN=0
AGENT_WHEEL="" # --agent-wheel: a local wheel instead of the Release's (testing before a release)
SERVER_WHEEL="" # --server-wheel: Sunroom's own, for On This Computer (testing before a release)
UNINSTALL=0
UNINSTALL_ARGS=()
ORIGINAL_ARGS=()

# Worked out while running
PLATFORM="" # pi | linux | macos | windows
MACHINE="this Pi" # "this computer" off a Pi, in the messages both share
BROWSER=""          # off a Pi: the browser the screen uses; empty until one is installed
MOUNTED_DMG=""      # a Mac: Google Chrome's disk image while it's attached
UV=""               # the uv that installs Sunroom Screen
AGENT_WHEEL_PATH="" # Sunroom Screen's checked wheel, under $WHEELS_DIR
SRC_DIR=""
TMP_DIR=""
CODENAME=""
SESSION="" # wayland | x11
SWITCH_TO_X11=0
DDC_BUS=""   # the monitor's I2C bus for DDC/CI brightness, when one answers
BACKLIGHT="" # the panel's backlight under /sys/class/backlight, when it has one
IMAGE_TAG=""
HAVE_TTY=0
LOGGING=0
STEP="getting started"
SUDO_KEEPALIVE_PID=""
TEE_PID=""

LAUNCHED=0             # a Mac: Sunroom Screen was running and started again on this version
TEMPLATE_TZ=""         # the compose file's TZ
TEMPLATE_ADVERTISED="" # the address devices open, printed on QR codes

# Remembered between runs for kiosk/uninstall.sh (see save_state)
LABWC_AUTOSTART_CREATED=0
TIME_WAIT_SYNC_BY_US=0
NM_DROPIN_WRITTEN=""
CMDLINE_FILE=""
CMDLINE_BACKUP=""
CMDLINE_KEYS=""
BACKLIGHT_RULE_WRITTEN=""
I2C_MODULES_WRITTEN=""

# ---------------------------------------------------------------------------- messages

lower() {
	printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

capitalized() {
	printf '%s' "$1" | awk '{ print toupper(substr($0, 1, 1)) substr($0, 2) }'
}

say() {
	printf '%s\n' "$*"
}

note() {
	printf '    %s\n' "$*"
}

warn() {
	printf '    Heads up: %s\n' "$*"
}

step() {
	STEP=$2
	printf '\n==> %s\n' "$1"
}

tidy() {
	local path=$1
	if [[ $path == "$HOME"/* ]]; then
		path="~${path#"$HOME"}"
	fi
	printf '%s' "$path"
}

die() {
	printf '\n' >&2
	printf '%s\n' "$@" >&2
	if ((LOGGING)); then
		printf '\nThe full log is in %s\n' "$(tidy "$LOG_FILE")" >&2
	fi
	exit 1
}

usage_error() {
	printf '%s\n' "$@" >&2
	printf 'Run it with --help to see every option.\n' >&2
	exit 2
}

on_error() {
	local status=$1 line=$2
	if ((BASH_SUBSHELL > 0)); then
		return 0
	fi
	printf '\nSomething went wrong while %s (line %s, exit code %s).\n' "$STEP" "$line" "$status" >&2
	printf 'Running the installer again is safe; it picks up where it stopped.\n' >&2
	if ((LOGGING)); then
		printf 'The full log is in %s\n' "$(tidy "$LOG_FILE")" >&2
	fi
}

log_only() {
	if ((LOGGING)); then
		printf '%s\n' "$*" >>"$LOG_FILE"
	fi
}

# Run a command with its chatter going to the log only; on failure, show its last lines.
quietly() {
	local out="$TMP_DIR/quietly.out" status=0
	"$@" >"$out" 2>&1 || status=$?
	cat "$out" >>"$LOG_FILE"
	if ((status != 0)); then
		tail -n 15 "$out"
	fi
	return "$status"
}

# ask_yes_no QUESTION DEFAULT(y|n) ANSWER-WITHOUT-KEYBOARD(y|n)
ask_yes_no() {
	local question=$1 default=$2 fallback=$3 hint answer word="no"
	if [[ $default == y ]]; then hint="[Y/n]"; else hint="[y/N]"; fi
	if ((!HAVE_TTY)); then
		if [[ $fallback == y ]]; then word="yes"; fi
		say "$question $hint (no keyboard to ask, so: $word)"
		[[ $fallback == y ]]
		return
	fi
	while true; do
		printf '%s %s ' "$question" "$hint" >/dev/tty
		answer=""
		IFS= read -r answer </dev/tty || true
		log_only "$question $hint ${answer:-<Enter>}"
		case $(lower "$answer") in
		"")
			[[ $default == y ]]
			return
			;;
		y | yes) return 0 ;;
		n | no) return 1 ;;
		*) printf 'Please answer y or n.\n' >/dev/tty ;;
		esac
	done
}

usage() {
	cat <<EOF
Sunroom installer $KIOSK_VERSION: this computer becomes a Sunroom screen, with
everything it needs (a browser too). A Raspberry Pi (Raspberry Pi OS 64-bit with desktop,
Bookworm or Trixie), another Linux computer with a desktop, or a Mac. Windows has install.ps1.

Usage: bash install.sh [options]

What to set up (with no option: the screen, which finds Sunroom on your network
itself, or asks for its address on the screen):
  --url URL                 The address of your Sunroom, so the screen doesn't look for it:
                            the one you open on your other devices, for example
                            http://192.168.1.20:8080 or https://calendar.example.com
  --with-sunroom            A Pi only: Sunroom on this Pi too, shown on its screen
  --server-only             A Pi only: Sunroom alone, no screen (Raspberry Pi OS Lite)
  --display-only            Only the screen, also on a Pi that runs Sunroom (a Pi
                            set up with --with-sunroom or --server-only keeps it when the
                            installer runs again with no option)

Options:
  --version X.Y.Z           With Sunroom on this Pi: run this version instead of the newest
                            (the screen's own software is always this installer's)
  --port N                  With Sunroom on this Pi: the port your devices use (default 8080)
  --output NAME             The screen's connector, for example HDMI-A-1
                            (default: the one with a screen plugged in)
  --rotate 0|90|180|270     Turn the picture for a screen mounted on its side
                            (90 = left, 180 = upside down, 270 = right)
  --force-hdmi WIDTHxHEIGHT Always drive the screen at this size, even when it is off
                            at startup, for example 1920x1080
  --brightness auto|ddc|sysfs|none
                            How the screen helper dims the screen in the evening:
                            ddc for a monitor that takes brightness over HDMI (DDC/CI),
                            sysfs for a panel with a backlight (Raspberry Pi Touch Display),
                            none to leave it to the page; auto (the default) picks
  --no-screen-helper        Never switch the screen itself off or change its brightness;
                            the page goes black or dim instead (for monitors whose touch
                            stops working while the screen is off)
  --x11                     Use the older X11 desktop instead of labwc (Wayland)
  --no-reboot               Don't offer to restart the Pi at the end
  --dry-run                 Say what it would do on this computer, and change nothing
  --agent-wheel FILE        Install Sunroom Screen from this wheel (just kiosk-build) instead
                            of the one in this version's GitHub Release (for testing)
  --server-wheel FILE       Keep Sunroom's own wheel (just server-build) for On This Computer
                            on the screen, instead of the Release's (for testing)
  --uninstall [--purge] [--yes]
                            Remove the screen setup; --purge also deletes Sunroom
                            and all its data from this Pi, --yes answers every question
  --help                    Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/$SUNROOM_REPO/main/kiosk/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/$SUNROOM_REPO/main/kiosk/install.sh | bash -s -- --with-sunroom
  bash kiosk/install.sh --url https://calendar.example.com --rotate 90
EOF
}

# ---------------------------------------------------------------------------- options

need_value() {
	if [[ $# -lt 2 || -z $2 || $2 == --* ]]; then
		usage_error "$1 needs a value after it, for example: $1 $(example_for "$1")"
	fi
}

example_for() {
	case $1 in
	--url) printf 'http://192.168.1.20:8080' ;;
	--version) printf '0.1.0' ;;
	--port) printf '8081' ;;
	--output) printf 'HDMI-A-1' ;;
	--rotate) printf '90' ;;
	--brightness) printf 'auto' ;;
	--force-hdmi) printf '1920x1080' ;;
	--agent-wheel) printf 'sunroom_kiosk-%s-py3-none-any.whl' "$KIOSK_VERSION" ;;
	--server-wheel) printf 'sunroom-%s-py3-none-any.whl' "$KIOSK_VERSION" ;;
	*) printf 'VALUE' ;;
	esac
}

parse_args() {
	while (($#)); do
		case $1 in
		--display-only) WANT_DISPLAY_ONLY=1 ;;
		--with-sunroom) WANT_WITH_SUNROOM=1 ;;
		--server-only) WANT_SERVER_ONLY=1 ;;
		--url)
			need_value "$@"
			URL=$2
			shift
			;;
		--url=*) URL=${1#*=} ;;
		--version)
			need_value "$@"
			VERSION=$2
			shift
			;;
		--version=*) VERSION=${1#*=} ;;
		--port)
			need_value "$@"
			PORT=$2
			PORT_GIVEN=1
			shift
			;;
		--port=*)
			PORT=${1#*=}
			PORT_GIVEN=1
			;;
		--output)
			need_value "$@"
			OUTPUT=$2
			OUTPUT_GIVEN=1
			SCREEN_OPTIONS_GIVEN=1
			shift
			;;
		--output=*)
			OUTPUT=${1#*=}
			OUTPUT_GIVEN=1
			SCREEN_OPTIONS_GIVEN=1
			;;
		--rotate)
			need_value "$@"
			ROTATE=$2
			SCREEN_OPTIONS_GIVEN=1
			shift
			;;
		--rotate=*)
			ROTATE=${1#*=}
			SCREEN_OPTIONS_GIVEN=1
			;;
		--brightness)
			need_value "$@"
			BRIGHTNESS=$2
			SCREEN_OPTIONS_GIVEN=1
			shift
			;;
		--brightness=*)
			BRIGHTNESS=${1#*=}
			SCREEN_OPTIONS_GIVEN=1
			;;
		--force-hdmi)
			need_value "$@"
			FORCE_HDMI=$2
			SCREEN_OPTIONS_GIVEN=1
			shift
			;;
		--force-hdmi=*)
			FORCE_HDMI=${1#*=}
			SCREEN_OPTIONS_GIVEN=1
			;;
		--no-screen-helper)
			SCREEN_HELPER="no"
			SCREEN_OPTIONS_GIVEN=1
			;;
		--no-reboot) NO_REBOOT=1 ;;
		--dry-run) DRY_RUN=1 ;;
		--agent-wheel)
			need_value "$@"
			AGENT_WHEEL=$2
			shift
			;;
		--agent-wheel=*) AGENT_WHEEL=${1#*=} ;;
		--server-wheel)
			need_value "$@"
			SERVER_WHEEL=$2
			shift
			;;
		--server-wheel=*) SERVER_WHEEL=${1#*=} ;;
		--x11)
			FORCE_X11=1
			SCREEN_OPTIONS_GIVEN=1
			;;
		--uninstall)
			UNINSTALL=1
			shift
			UNINSTALL_ARGS+=("$@")
			return 0
			;;
		--purge | --yes) UNINSTALL_ARGS+=("$1") ;;
		-h | --help)
			usage
			exit 0
			;;
		*) usage_error "I don't know the option \"$1\"." ;;
		esac
		shift
	done
}

validate_args() {
	local previous
	if ((${#UNINSTALL_ARGS[@]})); then
		usage_error "--purge and --yes only go with --uninstall, for example: bash install.sh --uninstall --purge"
	fi
	if ((WANT_DISPLAY_ONLY + WANT_WITH_SUNROOM + WANT_SERVER_ONLY > 1)); then
		usage_error "Choose one of --with-sunroom, --server-only and --display-only." \
			"With none of them, the installer sets up the screen alone."
	fi
	if [[ $PLATFORM != pi ]] && ((WANT_WITH_SUNROOM || WANT_SERVER_ONLY)); then
		usage_error "--with-sunroom and --server-only are for a Raspberry Pi; here the installer sets up the screen." \
			"To run Sunroom on this computer, use Docker (docs/DEPLOY.md)."
	fi
	if ((WANT_WITH_SUNROOM || WANT_SERVER_ONLY)) && [[ -n $URL ]]; then
		usage_error "--url is the address of Sunroom on another computer, so it doesn't go with --with-sunroom or --server-only."
	fi
	if [[ -n $AGENT_WHEEL && ! -f $AGENT_WHEEL ]]; then
		usage_error "--agent-wheel: there's no file at $AGENT_WHEEL."
	fi
	if [[ -n $SERVER_WHEEL ]]; then
		[[ -f $SERVER_WHEEL ]] || usage_error "--server-wheel: there's no file at $SERVER_WHEEL."
		[[ $(basename "$SERVER_WHEEL") == "sunroom-$KIOSK_VERSION-py3-none-any.whl" ]] ||
			usage_error "--server-wheel wants sunroom-$KIOSK_VERSION-py3-none-any.whl (just server-build makes it)."
	fi
	if ((WANT_SERVER_ONLY)); then
		MODE="server"
	elif ((WANT_WITH_SUNROOM)); then
		MODE="all"
	elif [[ $PLATFORM == pi ]] && ((!WANT_DISPLAY_ONLY)); then
		# A Pi that runs Sunroom from an earlier install keeps it (before ADR 0037, no option
		# meant Sunroom and the screen), unless --url points the screen at another one.
		previous=$(previous_mode)
		if [[ $previous == all || $previous == server ]]; then
			if [[ -n $URL ]]; then
				say "Note: --url given, so this Pi will only be the screen (as with --display-only)."
			else
				MODE=$previous
				KEPT_MODE=1
			fi
		fi
	fi
	if [[ -n $URL ]]; then
		URL="${URL%/}"
		URL="${URL%/display}"
		URL=$(lower "$URL")
		if [[ ! $URL =~ ^https?://[a-z0-9.-]+(:[0-9]{1,5})?$ ]]; then
			usage_error "\"$URL\" doesn't look like the address of Sunroom." \
				"Use the address you open on your other devices, for example http://192.168.1.20:8080 or https://calendar.example.com"
		fi
	fi
	if [[ -n $VERSION ]]; then
		VERSION=${VERSION#v}
		[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage_error "--version wants a version number like 0.1.0 (got \"$VERSION\")."
	fi
	if [[ ! $PORT =~ ^[0-9]{1,5}$ ]] || ((PORT < 1 || PORT > 65535)); then
		usage_error "--port wants a number between 1 and 65535 (got \"$PORT\")."
	fi
	if [[ -n $OUTPUT && ! $OUTPUT =~ ^[A-Za-z0-9-]+$ ]]; then
		usage_error "--output wants a connector name like HDMI-A-1, HDMI-A-2 or DSI-1 (got \"$OUTPUT\")."
	fi
	case $ROTATE in
	0 | 90 | 180 | 270) ;;
	*) usage_error "--rotate wants 0, 90, 180 or 270 (got \"$ROTATE\")." ;;
	esac
	case $BRIGHTNESS in
	auto | ddc | sysfs | none) ;;
	*) usage_error "--brightness wants auto, ddc, sysfs or none (got \"$BRIGHTNESS\")." ;;
	esac
	if [[ -n $FORCE_HDMI && ! $FORCE_HDMI =~ ^[0-9]{3,4}x[0-9]{3,4}$ ]]; then
		usage_error "--force-hdmi wants a screen size like 1920x1080 (got \"$FORCE_HDMI\")."
	fi
	if [[ $MODE == server ]] && ((SCREEN_OPTIONS_GIVEN)); then
		say "Note: Sunroom alone (--server-only) sets up no screen, so the screen options are ignored."
	fi
	if [[ $MODE == display ]] && ((PORT_GIVEN)); then
		say "Note: --port is for Sunroom on a Pi (--with-sunroom); the screen alone ignores it (the port is part of --url)."
	fi
	if [[ $MODE == display && -n $VERSION ]]; then
		say "Note: --version picks the Sunroom that runs on a Pi (--with-sunroom); the screen alone ignores it."
	fi
	if [[ $PLATFORM != pi ]] && { ((OUTPUT_GIVEN || FORCE_X11)) || [[ $ROTATE != 0 || -n $FORCE_HDMI ]]; }; then
		if [[ $PLATFORM == macos ]]; then
			say "Note: --output, --rotate, --force-hdmi and --x11 are for a Raspberry Pi; on $MACHINE, System Settings → Displays turns the picture."
		else
			say "Note: --output, --rotate, --force-hdmi and --x11 are for a Raspberry Pi; on $MACHINE, the screen's Settings → This Screen → Rotation turns the picture."
		fi
		OUTPUT=""
		ROTATE=0
		FORCE_HDMI=""
		FORCE_X11=0
	fi
}

# ---------------------------------------------------------------------------- plumbing

refuse_root() {
	if [[ $(id -u) -eq 0 ]]; then
		die "Please run the installer as your normal user, without sudo." \
			"It asks for sudo by itself when it needs to. For example:" \
			"  bash kiosk/install.sh"
	fi
}

detect_tty() {
	if { : </dev/tty; } 2>/dev/null; then
		HAVE_TTY=1
	fi
}

setup_logging() {
	mkdir -p "$STATE_DIR"
	printf '\n----- %s  install.sh %s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$KIOSK_VERSION" "${ORIGINAL_ARGS[*]-}" >>"$LOG_FILE"
	exec > >(tee -a "$LOG_FILE") 2>&1
	TEE_PID=$!
	LOGGING=1
}

cleanup() {
	if [[ -n $SUDO_KEEPALIVE_PID ]]; then
		kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
	fi
	if [[ -n $MOUNTED_DMG ]]; then
		hdiutil detach "$MOUNTED_DMG" -force -quiet 2>/dev/null || true
	fi
	if [[ -n $TMP_DIR && -d $TMP_DIR ]]; then
		rm -rf "$TMP_DIR"
	fi
	# Let tee finish writing, so the last lines don't appear after the shell prompt.
	if [[ -n $TEE_PID ]]; then
		exec 1>&- 2>&-
		wait "$TEE_PID" 2>/dev/null || true
	fi
}

# On a Pi, for the whole run; on another Linux computer, to install a browser.
start_sudo() {
	local fix="Your account needs to be allowed to use sudo (the first account on a Pi is)."
	if [[ $PLATFORM != pi ]]; then
		fix="Your account needs to be allowed to use sudo; or install Chromium yourself, then run this again."
	fi
	if ! command -v sudo >/dev/null 2>&1; then
		if [[ $PLATFORM == pi ]]; then
			die "This needs sudo, which isn't installed. Raspberry Pi OS includes it; is this Raspberry Pi OS?"
		fi
		die "Installing a browser needs sudo, which isn't installed here." \
			"Install Chromium yourself (as root), then run this again."
	fi
	if ! sudo -n true 2>/dev/null; then
		note "Some steps need administrator rights, so sudo may ask for your password."
		sudo -v || die "sudo didn't accept the password, so the installer can't continue." "$fix"
	fi
	# Keep sudo's timestamp fresh during long downloads; quiet, and gone when we are.
	(
		trap - ERR
		set +e
		while kill -0 "$$" 2>/dev/null; do
			sudo -n -v 2>/dev/null
			sleep 50
		done
	) >/dev/null 2>&1 &
	SUDO_KEEPALIVE_PID=$!
}

user_systemctl() {
	XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" systemctl --user "$@"
}

header_comment() {
	printf '# Written by the Sunroom installer (kiosk/install.sh %s). Running it again replaces this file.\n' "$KIOSK_VERSION"
}

# Copy a file from the kiosk folder with a version header after any #! line.
stamp_file() {
	local src=$1 first=""
	IFS= read -r first <"$src" || true
	if [[ $first == '#!'* ]]; then
		printf '%s\n' "$first"
		header_comment
		tail -n +2 "$src"
	else
		header_comment
		cat "$src"
	fi
}

# A file from kiosk/files with its placeholders filled in (values never hold a "|").
render() {
	sed -e "s|@VERSION@|$KIOSK_VERSION|g" \
		-e "s|@USER@|$(id -un)|g" \
		-e "s|@IMAGE@|$SUNROOM_IMAGE|g" \
		-e "s|@TAG@|${IMAGE_TAG:-latest}|g" \
		-e "s|@PORT@|$PORT|g" \
		-e "s|@TZ@|${TEMPLATE_TZ:-Etc/UTC}|g" \
		-e "s|@ADVERTISED@|${TEMPLATE_ADVERTISED:-}|g" \
		-e "s|@HOME@|$HOME|g" \
		"$1"
}

# install_template SRC DEST MODE [root]: render, stamp and install a file from kiosk/files.
install_template() {
	local src=$1 dest=$2 mode=$3 owner=${4:-} tmp
	tmp=$(mktemp "$TMP_DIR/template.XXXXXX")
	render "$src" >"$tmp"
	install_stamped "$tmp" "$dest" "$mode" "$owner"
}

# install_stamped SRC DEST MODE [root]
install_stamped() {
	local src=$1 dest=$2 mode=$3 owner=${4:-} tmp
	tmp=$(mktemp "$TMP_DIR/stamped.XXXXXX")
	stamp_file "$src" >"$tmp"
	if [[ $owner == root ]]; then
		sudo install -o root -g root -m "$mode" "$tmp" "$dest"
	else
		mkdir -p "$(dirname "$dest")"
		install -m "$mode" "$tmp" "$dest"
	fi
}

pi_hostname() {
	local name
	name=$(hostname -s 2>/dev/null || hostname)
	lower "$name"
}

pi_ip() {
	local dev ip=""
	dev=$(ip -4 route show default 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") {print $(i + 1); exit}}')
	if [[ -n $dev ]]; then
		ip=$(ip -4 -o addr show dev "$dev" scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1]; exit}')
	fi
	if [[ -z $ip ]]; then
		ip=$(hostname -I 2>/dev/null | awk '{print $1}')
	fi
	printf '%s' "$ip"
}

# What an earlier run set up (its STATE_MODE: display, all or server), empty without one. Read
# in a child bash, as existing_setting reads the screen's settings, so nothing else reaches this
# run before validate_args has decided.
previous_mode() {
	[[ -r $STATE_FILE ]] || return 0
	# shellcheck disable=SC2016 # expanded by the child bash, not this one
	bash -c 'set +u; . "$1" >/dev/null 2>&1; printf "%s" "${STATE_MODE:-}"' _ "$STATE_FILE" 2>/dev/null || true
}

load_previous_state() {
	if [[ -r $STATE_FILE ]]; then
		# shellcheck source=/dev/null
		. "$STATE_FILE"
	fi
	LABWC_AUTOSTART_CREATED=${STATE_LABWC_AUTOSTART_CREATED:-0}
	TIME_WAIT_SYNC_BY_US=${STATE_TIME_WAIT_SYNC_BY_US:-0}
	NM_DROPIN_WRITTEN=${STATE_NM_DROPIN:-}
	CMDLINE_FILE=${STATE_CMDLINE_FILE:-}
	CMDLINE_BACKUP=${STATE_CMDLINE_BACKUP:-}
	CMDLINE_KEYS=${STATE_CMDLINE_KEYS:-}
	BACKLIGHT_RULE_WRITTEN=${STATE_BACKLIGHT_RULE:-}
	I2C_MODULES_WRITTEN=${STATE_I2C_MODULES:-}
}

save_state() {
	local tmp="$TMP_DIR/install-state"
	{
		printf '# What the Sunroom installer (kiosk/install.sh %s) changed outside its own files,\n' "$KIOSK_VERSION"
		printf '# read by kiosk/uninstall.sh to put things back. Rewritten on every run.\n'
		printf 'STATE_MODE=%q\n' "$MODE"
		printf 'STATE_SESSION=%q\n' "$SESSION"
		printf 'STATE_LABWC_AUTOSTART_CREATED=%q\n' "$LABWC_AUTOSTART_CREATED"
		printf 'STATE_TIME_WAIT_SYNC_BY_US=%q\n' "$TIME_WAIT_SYNC_BY_US"
		printf 'STATE_NM_DROPIN=%q\n' "$NM_DROPIN_WRITTEN"
		printf 'STATE_CMDLINE_FILE=%q\n' "$CMDLINE_FILE"
		printf 'STATE_CMDLINE_BACKUP=%q\n' "$CMDLINE_BACKUP"
		printf 'STATE_CMDLINE_KEYS=%q\n' "$CMDLINE_KEYS"
		printf 'STATE_BACKLIGHT_RULE=%q\n' "$BACKLIGHT_RULE_WRITTEN"
		printf 'STATE_I2C_MODULES=%q\n' "$I2C_MODULES_WRITTEN"
	} >"$tmp"
	mkdir -p "$STATE_DIR"
	install -m 0644 "$tmp" "$STATE_FILE"
}

# ---------------------------------------------------------------------------- step 0: checks

# Which kind of computer this is: a Raspberry Pi (with Raspberry Pi OS: the screen, Sunroom or
# both), another Linux computer (the screen only), a Mac, or Windows (install.ps1).
detect_platform() {
	MACHINE="this computer"
	case $(uname -s) in
	Darwin)
		PLATFORM="macos"
		MACHINE="this Mac"
		;;
	Linux)
		if grep -qi 'raspberry pi' /proc/device-tree/model 2>/dev/null && command -v raspi-config >/dev/null 2>&1; then
			PLATFORM="pi"
			MACHINE="this Pi"
		else
			PLATFORM="linux"
		fi
		;;
	MINGW* | MSYS* | CYGWIN*) PLATFORM="windows" ;;
	*) PLATFORM="unknown" ;;
	esac
}

check_platform() {
	local arch
	arch=$(dpkg --print-architecture 2>/dev/null || uname -m)
	case $arch in
	arm64 | aarch64) ;;
	*)
		die "Sunroom needs the 64-bit version of Raspberry Pi OS (this Pi runs the $arch version)." \
			"Install \"Raspberry Pi OS (64-bit)\" with Raspberry Pi Imager, then run this again."
		;;
	esac
	[[ -r /etc/os-release ]] || die "This doesn't look like Raspberry Pi OS (there is no /etc/os-release)."
	# shellcheck source=/dev/null
	CODENAME=$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-}")
	case $CODENAME in
	bookworm | trixie) ;;
	*)
		die "This installer works on Raspberry Pi OS Bookworm or Trixie; this Pi runs \"${CODENAME:-something else}\"." \
			"Install the current Raspberry Pi OS (64-bit) with Raspberry Pi Imager, then run this again."
		;;
	esac
	note "Raspberry Pi OS $(capitalized "$CODENAME"), 64-bit."
}

check_disk() {
	local free_kb
	free_kb=$(df -Pk / | awk 'NR == 2 {print $4}')
	if [[ ! $free_kb =~ ^[0-9]+$ ]] || ((free_kb < 2 * 1024 * 1024)); then
		die "This Pi needs at least 2 GB of free space; it has about $((${free_kb:-0} / 1024)) MB." \
			"Use a bigger memory card or SSD, or remove programs you don't need, then run this again."
	fi
	note "Free space: $((free_kb / 1024 / 1024)) GB."
}

check_internet() {
	local try url
	for try in 1 2 3; do
		for url in https://deb.debian.org/debian/ https://archive.raspberrypi.com/debian/ https://github.com/; do
			if curl -fsS --max-time 10 -o /dev/null "$url" 2>/dev/null; then
				note "Internet: OK."
				return 0
			fi
		done
		if ((try < 3)); then
			sleep 5
		fi
	done
	die "$(capitalized "$MACHINE") can't reach the internet." \
		"Check the Wi-Fi or network cable, and that the date and time are right (type: date)," \
		"then run the installer again."
}

check_remote_server() {
	local code
	code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$URL/api/health" 2>/dev/null || true)
	if [[ $code == 200 ]]; then
		note "Sunroom answered at $URL."
	else
		warn "Sunroom didn't answer at $URL just now. The screen keeps trying when it starts;" \
			"if it says it can't reach Sunroom, check that this address opens on another device."
	fi
}

# Which desktop session will run after a restart. Mirrors raspi-config, which reads
# lightdm's autologin-session/user-session when switching and pgrep labwc/wayfire for
# the running one: rpd-labwc or LXDE-pi-labwc = labwc, LXDE-pi-wayfire = Wayfire (older
# Bookworm), rpd-x or LXDE-pi-x = X11.
lightdm_value() {
	local key=$1 file found value=""
	for file in /usr/share/lightdm/lightdm.conf.d/*.conf /etc/xdg/lightdm/lightdm.conf.d/*.conf \
		/etc/lightdm/lightdm.conf.d/*.conf /etc/lightdm/lightdm.conf; do
		[[ -r $file ]] || continue
		found=$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1)
		if [[ -n $found ]]; then
			value=$found
		fi
	done
	printf '%s' "${value%%[[:space:]]*}"
}

lightdm_session() {
	local session
	session=$(lightdm_value autologin-session)
	if [[ -z $session ]]; then
		session=$(lightdm_value user-session)
	fi
	printf '%s' "$session"
}

session_kind() {
	case $1 in
	"") ;;
	*labwc*) printf 'labwc' ;;
	*wayfire*) printf 'wayfire' ;;
	*)
		if [[ -e /usr/share/xsessions/$1.desktop ]]; then
			printf 'x11'
		elif [[ -e /usr/share/wayland-sessions/$1.desktop ]]; then
			printf 'other'
		fi
		;;
	esac
}

running_session_kind() {
	if pgrep -x labwc >/dev/null 2>&1; then
		printf 'labwc'
	elif pgrep -x wayfire >/dev/null 2>&1; then
		printf 'wayfire'
	elif pgrep -x Xorg >/dev/null 2>&1 || pgrep -x openbox >/dev/null 2>&1; then
		printf 'x11'
	fi
}

installed_session_kind() {
	if [[ -e /usr/share/wayland-sessions/rpd-labwc.desktop || -e /usr/share/wayland-sessions/LXDE-pi-labwc.desktop ]]; then
		printf 'labwc'
	elif [[ -e /usr/share/xsessions/rpd-x.desktop || -e /usr/share/xsessions/LXDE-pi-x.desktop ]]; then
		printf 'x11'
	fi
}

has_x11_session() {
	[[ -e /usr/share/xsessions/rpd-x.desktop || -e /usr/share/xsessions/LXDE-pi-x.desktop ]]
}

has_desktop() {
	local file
	[[ -e /etc/init.d/lightdm ]] || return 1
	for file in /usr/share/xsessions/*.desktop /usr/share/wayland-sessions/*.desktop; do
		if [[ -e $file ]]; then
			return 0
		fi
	done
	return 1
}

labwc_switch_command() {
	if [[ $CODENAME == bookworm ]]; then
		if [[ -x /usr/bin/labwc ]]; then
			printf 'sudo raspi-config nonint do_wayland W3'
		else
			printf 'sudo apt update && sudo apt full-upgrade -y && sudo raspi-config nonint do_wayland W3'
		fi
	else
		printf 'sudo raspi-config nonint do_wayland W2'
	fi
}

detect_session() {
	local configured kind
	if ! command -v raspi-config >/dev/null 2>&1 || ! has_desktop; then
		die "This Pi has no desktop, so it can't drive a screen." \
			"To run only Sunroom here, run the installer again with --server-only." \
			"For a screen, install \"Raspberry Pi OS (64-bit)\" (the one with desktop) with Raspberry Pi Imager."
	fi
	configured=$(lightdm_session)
	if ((FORCE_X11)); then
		has_x11_session || die "You asked for the X11 desktop (--x11), but it isn't installed on this Pi." \
			"Run the installer without --x11 to use the standard labwc desktop."
		if [[ $(session_kind "$configured") != x11 ]]; then
			SWITCH_TO_X11=1
		fi
		SESSION="x11"
		note "Desktop: X11 (as asked with --x11)."
		return
	fi
	kind=$(session_kind "$configured")
	if [[ -z $kind ]]; then
		kind=$(running_session_kind)
	fi
	if [[ -z $kind ]]; then
		kind=$(installed_session_kind)
	fi
	case $kind in
	labwc)
		SESSION="wayland"
		note "Desktop: labwc (Wayland)."
		;;
	x11)
		SESSION="x11"
		note "Desktop: X11."
		;;
	wayfire)
		die "This Pi's desktop uses Wayfire, which the screen doesn't support." \
			"Switch to the newer labwc desktop with this one line, restart, then run the installer again:" \
			"  $(labwc_switch_command)"
		;;
	*)
		die "This Pi's desktop (${configured:-unknown}) isn't one the screen supports." \
			"Switch to the standard labwc desktop with this one line, restart, then run the installer again:" \
			"  $(labwc_switch_command)"
		;;
	esac
}

# The connector with a screen plugged in, by its kernel name (HDMI-A-1, DSI-1, ...).
detect_output() {
	local status name pass
	for pass in hdmi any; do
		for status in /sys/class/drm/card*-*/status; do
			[[ -r $status ]] || continue
			[[ $(<"$status") == connected ]] || continue
			name=${status%/status}
			name=${name##*/}
			name=${name#card*-}
			case $name in
			Writeback-*) continue ;;
			HDMI-*) ;;
			*) [[ $pass == any ]] || continue ;;
			esac
			printf '%s' "$name"
			return 0
		done
	done
	return 1
}

resolve_output() {
	if ((OUTPUT_GIVEN)); then
		note "Screen connector: $OUTPUT (as given)."
	elif OUTPUT=$(detect_output); then
		note "Screen connector: $OUTPUT."
	else
		OUTPUT="HDMI-A-1"
		note "No screen detected right now; assuming it will be on $OUTPUT."
	fi
}

# The first-boot software update (or the desktop's update check) holds apt's locks for a
# while; apt-get would fail on them, so wait.
apt_busy() {
	if command -v python3 >/dev/null 2>&1; then
		sudo python3 - <<'PY'
import fcntl
import os
import sys

for path in ("/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock",
             "/var/lib/apt/lists/lock", "/var/cache/apt/archives/lock"):
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        continue
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the same fcntl lock apt and dpkg take
        fcntl.lockf(fd, fcntl.LOCK_UN)
    except OSError:
        sys.exit(0)  # busy
    finally:
        os.close(fd)
sys.exit(1)  # free
PY
		return
	fi
	pgrep -x apt-get >/dev/null 2>&1 || pgrep -x apt >/dev/null 2>&1 || pgrep -x dpkg >/dev/null 2>&1 ||
		pgrep -f unattended-upgrade >/dev/null 2>&1
}

wait_for_apt() {
	local waited=0
	if ! apt_busy; then
		return 0
	fi
	note "$(capitalized "$MACHINE") is installing its own updates (normal right after the first start). Waiting for it to finish..."
	while apt_busy; do
		sleep 5
		waited=$((waited + 5))
		if ((waited % 60 == 0)); then
			note "Still waiting ($((waited / 60)) min)..."
		fi
		if ((waited >= 1800)); then
			die "$(capitalized "$MACHINE")'s own software update has been running for 30 minutes." \
				"Restart $MACHINE (sudo reboot), wait five minutes, then run the installer again."
		fi
	done
	note "Its own update finished."
}

# ---------------------------------------------------------------------------- the kiosk folder

has_kiosk_files() {
	local dir=$1 file
	for file in labwc-rule.py update.sh uninstall.sh files/avahi/sunroom.service \
		files/systemd/sunroom-kiosk.service files/labwc/autostart-block files/xdg/sunroom-kiosk.desktop \
		files/udev/90-sunroom-kiosk-backlight.rules files/modules-load/sunroom-kiosk-i2c.conf \
		files/NetworkManager/zz-sunroom-kiosk-wifi.conf files/sunroom/docker-compose.yml \
		files/sunroom/env files/sudoers/sunroom-kiosk files/sunroom-kiosk-root \
		files/launchd/app.sunroom.kiosk.plist; do
		[[ -f $dir/$file ]] || return 1
	done
}

download_kiosk_files() {
	local ref url tarball args
	# This installer's own version: its files and Sunroom Screen's wheel come from one release.
	ref="refs/tags/v$KIOSK_VERSION"
	url="https://codeload.github.com/$SUNROOM_REPO/tar.gz/$ref"
	tarball="$TMP_DIR/kiosk.tar.gz"
	args=""
	if ((${#ORIGINAL_ARGS[@]})); then
		args=$(printf ' %q' "${ORIGINAL_ARGS[@]}")
	fi
	note "Downloading the Sunroom Screen files (version $KIOSK_VERSION)..."
	if ! curl -fsSL --retry 3 --connect-timeout 15 -o "$tarball" "$url" 2>>"$LOG_FILE"; then
		die "I couldn't download the rest of the Sunroom Screen files from GitHub." \
			"Either GitHub can't be reached right now, or version $KIOSK_VERSION isn't published yet." \
			"Instead, copy the whole kiosk folder to $MACHINE (for example: scp -r kiosk YOUR-USER@sunroom.local:)" \
			"and run the installer from that copy:" \
			"  bash kiosk/install.sh${args}"
	fi
	mkdir -p "$TMP_DIR/src"
	# All of it: a Mac's tar has no --wildcards, and the repository is small.
	if ! tar -xzf "$tarball" -C "$TMP_DIR/src" --strip-components=1 2>/dev/null; then
		die "The download from GitHub has no Sunroom Screen files in it, or it was damaged." \
			"Run the installer again."
	fi
	SRC_DIR="$TMP_DIR/src/kiosk"
	has_kiosk_files "$SRC_DIR" || die "The download from GitHub is missing some Sunroom Screen files." \
		"Copy the kiosk folder to $MACHINE and run: bash kiosk/install.sh${args}"
}

get_kiosk_files() {
	local dir
	if [[ -n $SCRIPT_PATH && -f $SCRIPT_PATH ]]; then
		dir=$(cd "$(dirname "$SCRIPT_PATH")" && pwd)
		if has_kiosk_files "$dir"; then
			SRC_DIR=$dir
			note "Using the Sunroom Screen files next to this installer ($(tidy "$dir"))."
			return
		fi
	fi
	download_kiosk_files
}

# ---------------------------------------------------------------------------- step 1: packages

pkg_installed() {
	# shellcheck disable=SC2016 # ${Status} is dpkg-query's format, not a shell variable
	[[ $(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true) == "install ok installed" ]]
}

# Offered by apt, as itself: Ubuntu's chromium-browser (1snap1) only installs the snap.
pkg_available() {
	local candidate
	candidate=$(apt-cache policy "$1" 2>/dev/null | awk '$1 == "Candidate:" {print $2; exit}')
	[[ -n $candidate && $candidate != "(none)" && $candidate != *snap* ]]
}

# Callers run wait_for_apt first (so its messages show); the lock timeout is a backstop.
apt_get() {
	sudo env DEBIAN_FRONTEND=noninteractive apt-get -q -o DPkg::Lock::Timeout=600 "$@"
}

install_packages() {
	local -a wanted=(curl ca-certificates jq qrencode) optional=() missing=()
	local pkg need_chromium=0
	if [[ $MODE != server ]]; then
		wanted+=(python3)
		if [[ $SESSION == wayland ]]; then
			wanted+=(wlr-randr)
			optional+=(wlopm) # the screen helper switches the screen off and on with it
		else
			wanted+=(x11-xserver-utils unclutter)
		fi
		if wants_ddc; then
			optional+=(ddcutil) # the screen helper sets a monitor's brightness with it
		fi
		if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
			need_chromium=1
		fi
	fi
	for pkg in "${wanted[@]}" ${optional[@]+"${optional[@]}"}; do
		if ! pkg_installed "$pkg"; then
			missing+=("$pkg")
		fi
	done
	if ((${#missing[@]} == 0 && !need_chromium)); then
		note "Everything it needs is already installed."
	else
		wait_for_apt
		note "Refreshing the list of available software..."
		quietly apt_get update || die "Couldn't refresh the list of available software." \
			"Check the internet connection and that the date and time are right (type: date), then run this again."
		if ((need_chromium)); then
			if pkg_available chromium; then
				missing+=(chromium)
			else
				missing+=(chromium-browser)
			fi
		fi
		local -a install_now=()
		for pkg in "${missing[@]}"; do
			if [[ $pkg == wlopm ]] && ! pkg_available wlopm; then
				note "Skipping wlopm (not offered for this Pi); the screen helper uses wlr-randr instead."
				continue
			fi
			if [[ $pkg == ddcutil ]] && ! pkg_available ddcutil; then
				note "Skipping ddcutil (not offered for this Pi); the page dims itself instead."
				continue
			fi
			install_now+=("$pkg")
		done
		if ((${#install_now[@]})); then
			wait_for_apt
			note "Installing: ${install_now[*]}"
			quietly apt_get install -y "${install_now[@]}" || die "Couldn't install: ${install_now[*]}" \
				"Check the internet connection, then run the installer again."
		fi
	fi
	if [[ $MODE != server && $SESSION == wayland ]]; then
		check_labwc_version
	fi
}

check_labwc_version() {
	local version
	# shellcheck disable=SC2016 # ${Version} is dpkg-query's format, not a shell variable
	version=$(dpkg-query -W -f='${Version}' labwc 2>/dev/null || true)
	if [[ -n $version ]] && dpkg --compare-versions "$version" lt 0.8.4; then
		warn "this Pi's desktop (labwc $version) is older than 0.8.4, so the mouse pointer may stay" \
			"visible on the screen. Bringing the Pi up to date fixes it: sudo apt update && sudo apt full-upgrade"
	fi
}

# ---------------------------------------------------------------------------- steps 2 and 3: Docker and Sunroom

install_docker() {
	local user
	user=$(id -un)
	if command -v docker >/dev/null 2>&1; then
		note "Docker is already installed."
	else
		note "Installing Docker, the tool that runs Sunroom (this takes a few minutes)..."
		curl -fsSL --retry 3 -o "$TMP_DIR/get-docker.sh" https://get.docker.com ||
			die "Couldn't download Docker's installer. Check the internet connection, then run this again."
		wait_for_apt
		quietly sudo sh "$TMP_DIR/get-docker.sh" || die "Docker's installer didn't finish. Its last messages are above." \
			"Running the Sunroom installer again is safe; it tries again."
	fi
	# Only a convenience for later (this script always uses sudo docker).
	if ! getent group docker >/dev/null 2>&1; then
		log_only "No docker group on this system; not adding $user to it."
	elif [[ " $(id -nG "$user") " != *" docker "* ]]; then
		sudo usermod -aG docker "$user"
		note "Added $user to the docker group (takes effect after the next login; until then use sudo docker)."
	fi
	sudo systemctl enable --now docker >/dev/null 2>&1 || die "Docker is installed but won't start." \
		"Restart the Pi (sudo reboot) and run the installer again."
	# Unverified: Docker installed some other way may lack "docker compose"; the plugin
	# package exists in Docker's own apt source, "docker-compose" in Debian's.
	if ! sudo docker compose version >/dev/null 2>&1; then
		note "Adding Docker's compose tool..."
		wait_for_apt
		quietly apt_get install -y docker-compose-plugin || quietly apt_get install -y docker-compose || true
		sudo docker compose version >/dev/null 2>&1 || die "Docker's compose tool is missing and couldn't be installed." \
			"Install it with:  sudo apt install docker-compose-plugin  then run the installer again."
	fi
}

compose() {
	sudo docker compose --project-directory "$SERVER_DIR" -f "$SERVER_DIR/docker-compose.yml" "$@"
}

# The tag in "image: scopexl/sunroom:<tag>" of an earlier install; empty when there is none.
existing_tag() {
	sudo test -f "$SERVER_DIR/docker-compose.yml" || return 0
	sudo awk -v image="$SUNROOM_IMAGE" '
		$1 == "image:" {
			value = $2
			gsub(/["\047]/, "", value)
			if (index(value, image ":") == 1) { print substr(value, length(image) + 2); exit }
		}' "$SERVER_DIR/docker-compose.yml"
}

write_stack() {
	local tz host previous
	previous=$(existing_tag || true)
	if [[ -n $VERSION ]]; then
		IMAGE_TAG=$VERSION
	elif [[ -n $previous ]]; then
		IMAGE_TAG=$previous
		if [[ $previous != latest ]]; then
			note "Keeping the Sunroom version this Pi already has ($previous). To change it: sudo /opt/sunroom/update.sh"
		fi
	else
		IMAGE_TAG="latest"
	fi
	tz=$(timedatectl show -p Timezone --value 2>/dev/null || true)
	if [[ ! $tz =~ ^[A-Za-z0-9_+/-]+$ ]]; then
		tz=$(cat /etc/timezone 2>/dev/null || true)
	fi
	if [[ ! $tz =~ ^[A-Za-z0-9_+/-]+$ ]]; then
		tz="Etc/UTC"
	fi
	host=$(pi_hostname)

	sudo install -d -m 0755 -o root -g root "$SERVER_DIR"
	TEMPLATE_TZ=$tz
	TEMPLATE_ADVERTISED="http://$host.local:$PORT"
	{
		header_comment
		render "$SRC_DIR/files/sunroom/docker-compose.yml"
	} >"$TMP_DIR/docker-compose.yml"
	if sudo test -f "$SERVER_DIR/docker-compose.yml" && ! sudo cmp -s "$TMP_DIR/docker-compose.yml" "$SERVER_DIR/docker-compose.yml"; then
		sudo cp -p "$SERVER_DIR/docker-compose.yml" "$SERVER_DIR/docker-compose.yml.previous"
		note "Saved the previous settings as $SERVER_DIR/docker-compose.yml.previous."
	fi
	sudo install -m 0644 -o root -g root "$TMP_DIR/docker-compose.yml" "$SERVER_DIR/docker-compose.yml"
	if sudo test -f "$SERVER_DIR/.env"; then
		sudo chown root:root "$SERVER_DIR/.env"
		sudo chmod 0600 "$SERVER_DIR/.env"
	else
		{
			header_comment | sed 's/ Running it again replaces this file./ It is created once and never overwritten./'
			render "$SRC_DIR/files/sunroom/env"
		} >"$TMP_DIR/env"
		sudo install -m 0600 -o root -g root "$TMP_DIR/env" "$SERVER_DIR/.env"
	fi
	install_stamped "$SRC_DIR/update.sh" "$SERVER_DIR/update.sh" 0755 root
	note "Wrote $SERVER_DIR/docker-compose.yml (Sunroom $IMAGE_TAG, port $PORT, time zone $tz)."
}

wait_for_health() {
	local url="http://localhost:$PORT/api/health" waited=0 code
	note "Waiting for Sunroom to answer (the first start can take a minute or two)..."
	while ((waited < HEALTH_TIMEOUT)); do
		code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || true)
		if [[ $code == 200 ]]; then
			note "Sunroom is up."
			return 0
		fi
		sleep 2
		waited=$((waited + 2))
		if ((waited % 30 == 0)); then
			note "Still starting ($waited seconds)..."
		fi
	done
	say "Sunroom's last 40 log lines:"
	sudo docker logs --tail 40 sunroom 2>&1 || true
	die "Sunroom didn't answer within $((HEALTH_TIMEOUT / 60)) minutes. Its last log lines are above." \
		"Running the installer again is safe; it continues from here."
}

start_stack() {
	local image="$SUNROOM_IMAGE:$IMAGE_TAG" output
	if sudo docker image inspect "$image" >/dev/null 2>&1; then
		note "Sunroom $IMAGE_TAG is already downloaded."
	else
		note "Downloading Sunroom ($image); the first time takes a few minutes..."
		compose pull || die "Couldn't download Sunroom ($image) from Docker Hub." \
			"Check the internet connection${VERSION:+ and that version $VERSION exists}, then run the installer again."
	fi
	note "Starting Sunroom..."
	if ! output=$(compose up -d 2>&1); then
		printf '%s\n' "$output"
		if grep -qiE 'address already in use|port is already allocated' <<<"$output"; then
			die "Another program on this Pi already uses port $PORT." \
				"Run the installer again with another port, for example: --port 8081"
		fi
		if grep -qi 'is already in use by container' <<<"$output"; then
			die "A container called sunroom already exists, perhaps from an earlier docker run." \
				"Remove it (your data in the sunroom_data volume stays):  sudo docker rm -f sunroom" \
				"then run the installer again."
		fi
		die "Sunroom didn't start; Docker's message is above." "Running the installer again is safe."
	fi
	printf '%s\n' "$output"
	wait_for_health
}

# Sunroom screens on this network find this server by itself through avahi, which Raspberry Pi
# OS runs (the server in its container can't announce itself: Docker's network keeps the
# announcement in). Without avahi the screens still find it by looking at every address.
write_avahi_service() {
	local note tmp="$TMP_DIR/sunroom.service"
	if ! sudo test -d "$(dirname "$AVAHI_SERVICE")"; then
		log_only "No $(dirname "$AVAHI_SERVICE"); Sunroom screens will find this Pi by its address."
		return 0
	fi
	note=$(header_comment | sed 's/^# //')
	sed -e "s|@PORT@|$PORT|" -e "s|@VERSION@|$KIOSK_VERSION|" -e "s|@NOTE@|$note|" \
		"$SRC_DIR/files/avahi/sunroom.service" >"$tmp"
	sudo install -m 0644 -o root -g root "$tmp" "$AVAHI_SERVICE"
	note "Sunroom screens on this network can find this Pi by themselves now."
}

# ---------------------------------------------------------------------------- step 4: the screen

install_helper_copies() {
	install_stamped "$SRC_DIR/uninstall.sh" "$SHARE_DIR/uninstall.sh" 0755
	install_stamped "$SRC_DIR/labwc-rule.py" "$SHARE_DIR/labwc-rule.py" 0755
}

# ---------------------------------------------------------------------------- Sunroom Screen

# uv installs Sunroom Screen and the Python it runs on (3.14, kept apart from the system's).
install_uv() {
	if command -v uv >/dev/null 2>&1; then
		UV=$(command -v uv)
		return 0
	fi
	if [[ -x $BIN_DIR/uv ]]; then
		UV="$BIN_DIR/uv"
		return 0
	fi
	note "Installing uv $UV_VERSION, which installs Sunroom Screen..."
	curl -LsSf --retry 3 -o "$TMP_DIR/uv-install.sh" "https://astral.sh/uv/$UV_VERSION/install.sh" ||
		die "Couldn't download uv's installer. Check the internet connection, then run this again."
	quietly env UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$BIN_DIR" sh "$TMP_DIR/uv-install.sh" ||
		die "uv's installer didn't finish; its last messages are above. Running this again is safe."
	UV="$BIN_DIR/uv"
}

sha256_of() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	else
		shasum -a 256 "$1" | awk '{print $1}'
	fi
}

# Sunroom Screen's wheel: --agent-wheel's, or this version's from its GitHub Release, checked
# against the Release's SHA256SUMS before anything installs it. Kept in $WHEELS_DIR, so an
# update can go back to it.
fetch_agent_wheel() {
	local name="sunroom_kiosk-$KIOSK_VERSION-py3-none-any.whl" base expected actual
	mkdir -p "$WHEELS_DIR"
	if [[ -n $AGENT_WHEEL ]]; then
		name=$(basename "$AGENT_WHEEL")
		cp "$AGENT_WHEEL" "$WHEELS_DIR/$name"
		AGENT_WHEEL_PATH="$WHEELS_DIR/$name"
		note "Using Sunroom Screen from $(tidy "$AGENT_WHEEL") (--agent-wheel: not checked against a release)."
		return 0
	fi
	base="https://github.com/$SUNROOM_REPO/releases/download/v$KIOSK_VERSION"
	if ! curl -fsSL --retry 3 -o "$TMP_DIR/SHA256SUMS" "$base/SHA256SUMS" 2>>"$LOG_FILE"; then
		die "Couldn't download Sunroom Screen $KIOSK_VERSION's checksums from GitHub." \
			"Either GitHub can't be reached right now, or this version's files are still being published" \
			"(it takes a few minutes after a release). Try again in a little while."
	fi
	expected=$(awk -v file="$name" '$2 == file || $2 == "*" file {print $1; exit}' "$TMP_DIR/SHA256SUMS")
	[[ $expected =~ ^[0-9a-f]{64}$ ]] || die "Sunroom Screen $KIOSK_VERSION isn't in its release's checksums." \
		"Try again in a little while; if it lasts, run the installer of another version."
	curl -fsSL --retry 3 -o "$TMP_DIR/$name" "$base/$name" 2>>"$LOG_FILE" ||
		die "Couldn't download Sunroom Screen $KIOSK_VERSION from GitHub. Check the internet connection, then run this again."
	actual=$(sha256_of "$TMP_DIR/$name")
	if [[ $actual != "$expected" ]]; then
		die "The download of Sunroom Screen didn't match its checksum, so it wasn't installed." \
			"Run the installer again; if it happens again, tell us on GitHub."
	fi
	install -m 0644 "$TMP_DIR/$name" "$WHEELS_DIR/$name"
	AGENT_WHEEL_PATH="$WHEELS_DIR/$name"
	note "Downloaded Sunroom Screen $KIOSK_VERSION and checked it."
}

# --server-wheel: Sunroom's own wheel, and its constraints from beside it, where Sunroom Screen
# looks first when On This Computer is chosen (agent local.py; not checked against a release).
keep_server_wheel() {
	local constraints
	[[ -n $SERVER_WHEEL ]] || return 0
	mkdir -p "$WHEELS_DIR"
	cp "$SERVER_WHEEL" "$WHEELS_DIR/"
	constraints="$(dirname "$SERVER_WHEEL")/sunroom-$KIOSK_VERSION-constraints.txt"
	if [[ -f $constraints ]]; then
		cp "$constraints" "$WHEELS_DIR/"
	fi
	note "Kept Sunroom from $(tidy "$SERVER_WHEEL") for On This Computer (--server-wheel: not checked against a release)."
}

install_agent() {
	install_uv
	fetch_agent_wheel
	keep_server_wheel
	# The bash launcher from before 0.13.0 sat where uv puts Sunroom Screen.
	if [[ -f $BIN_DIR/sunroom-kiosk && ! -L $BIN_DIR/sunroom-kiosk ]]; then
		rm -f "$BIN_DIR/sunroom-kiosk"
	fi
	note "Installing Sunroom Screen (with its own Python; the first time takes a minute)..."
	quietly env UV_TOOL_BIN_DIR="$BIN_DIR" "$UV" tool install --reinstall --force --python 3.14 "$AGENT_WHEEL_PATH" ||
		die "Couldn't install Sunroom Screen; the messages above say why. Running the installer again is safe."
	"$BIN_DIR/sunroom-kiosk" --version >/dev/null 2>&1 ||
		die "Sunroom Screen was installed but doesn't start. The full log has the details."
	note "Installed Sunroom Screen $KIOSK_VERSION."
}

# One root helper for the few root tasks (the browser's policy; on a Pi, the system's updates and
# update.sh too), allowed by sudoers for this user only, and checked by visudo first.
install_root_helper() {
	local sudoers="$TMP_DIR/sudoers"
	install_template "$SRC_DIR/files/sunroom-kiosk-root" "$ROOT_HELPER" 0755 root
	{
		header_comment
		render "$SRC_DIR/files/sudoers/sunroom-kiosk"
	} >"$sudoers"
	sudo visudo -cqf "$sudoers" >/dev/null 2>&1 ||
		die "The sudoers file for Sunroom Screen didn't check out (visudo); nothing was changed there."
	sudo install -m 0440 -o root -g root "$sudoers" "$SUDOERS_FILE"
	if [[ $PLATFORM == pi ]]; then
		note "Sunroom Screen may update this Pi and set the browser's settings (and nothing else as root)."
	else
		note "Sunroom Screen may set the browser's settings when its address changes (and nothing else as root)."
	fi
}

# Before 0.13.0 the screen helper and the 04:00 browser restart had units of their own; Sunroom
# Screen does both now.
retire_old_screen() {
	local unit retired=0
	for unit in sunroom-screen.service sunroom-kiosk-restart.timer sunroom-kiosk-restart.service; do
		if [[ -e $UNIT_DIR/$unit ]]; then
			user_systemctl disable --now "$unit" >/dev/null 2>&1 || true
			rm -f "$UNIT_DIR/$unit" "$UNIT_DIR/timers.target.wants/$unit"
			retired=1
		fi
	done
	if [[ -e $BIN_DIR/sunroom-screen ]]; then
		rm -f "$BIN_DIR/sunroom-screen"
		retired=1
	fi
	if ((retired)); then
		note "Sunroom Screen now does what the screen helper and the nightly restart did; their own services are gone."
	fi
}

# What the agent saved in the screen's settings before (an address it found, its id, Updates):
# kept when the installer runs again. Read in a child bash, as the uninstaller reads the file,
# so nothing in it reaches this run.
existing_setting() {
	[[ -r $CONFIG_DIR/config ]] || return 0
	# shellcheck disable=SC2016 # expanded by the child bash, not this one
	bash -c 'set +u; . "$1" >/dev/null 2>&1; printf "%s" "${!2:-}"' _ "$CONFIG_DIR/config" "$1" 2>/dev/null || true
}

write_kiosk_config() {
	local url found id check tmp="$TMP_DIR/kiosk-config"
	if [[ $MODE == display ]]; then
		url=$URL
		found="typed"
		if [[ -z $url ]]; then
			# No --url: keep what the screen found or was told before; with none, it looks.
			url=$(existing_setting SUNROOM_URL)
			found=$(existing_setting SUNROOM_FOUND)
		fi
	else
		url="http://localhost:$PORT"
		found="local"
	fi
	if [[ -n $url && -z $found ]]; then
		found="typed" # an address from before 0.13.0 was always given with --url
	fi
	id=""
	if [[ -n $url && $url == "$(existing_setting SUNROOM_URL)" ]]; then
		id=$(existing_setting SUNROOM_ID)
	fi
	check=$(existing_setting SUNROOM_UPDATE_CHECK)
	{
		header_comment
		printf '# Sunroom Screen keeps this up to date (This Screen on the wall changes it). After a change\n'
		printf '# by hand: systemctl --user restart sunroom-kiosk\n'
		printf 'SUNROOM_URL=%q\n' "$url"
		printf 'SUNROOM_ID=%q\n' "$id"
		printf 'SUNROOM_FOUND=%q\n' "${url:+$found}"
		printf 'SUNROOM_SESSION=%q\n' "$SESSION"
		printf 'SUNROOM_OUTPUT=%q\n' "$OUTPUT"
		printf 'SUNROOM_ROTATE=%q\n' "$ROTATE"
		printf '# The screen helper (yes or no) switches the screen off at night. How it dims it:\n'
		printf '# auto, ddc (DDC/CI on I2C bus SUNROOM_DDC_BUS), sysfs (the backlight SUNROOM_BACKLIGHT\n'
		printf '# under /sys/class/backlight) or none (the page dims itself). See docs/KIOSK.md.\n'
		printf 'SUNROOM_SCREEN_HELPER=%q\n' "$SCREEN_HELPER"
		printf 'SUNROOM_BRIGHTNESS=%q\n' "$BRIGHTNESS"
		printf 'SUNROOM_DDC_BUS=%q\n' "$DDC_BUS"
		printf 'SUNROOM_BACKLIGHT=%q\n' "$BACKLIGHT"
		printf 'SUNROOM_MODE=%q\n' "$MODE"
		printf '# nightly (installed overnight) or off; empty is the default, installed overnight.\n'
		printf 'SUNROOM_UPDATE_CHECK=%q\n' "$check"
	} >"$tmp"
	mkdir -p "$CONFIG_DIR"
	install -m 0644 "$tmp" "$CONFIG_DIR/config"
	if [[ -n $url ]]; then
		note "Saved the screen's settings in $(tidy "$CONFIG_DIR/config") (it opens $url)."
	else
		note "Saved the screen's settings in $(tidy "$CONFIG_DIR/config"); it finds its Sunroom itself."
	fi
}

install_units() {
	retire_old_screen
	install_template "$SRC_DIR/files/systemd/sunroom-kiosk.service" "$UNIT_DIR/sunroom-kiosk.service" 0644
	user_systemctl daemon-reload >/dev/null 2>&1 || true
	# Sunroom Screen from an earlier install switches to this version now.
	user_systemctl try-restart sunroom-kiosk.service >/dev/null 2>&1 || true
	note "Installed Sunroom Screen's service; the desktop starts it at login."
}

# Print FILE without the managed block. An unfinished block is printed back unchanged.
strip_block() {
	awk -v begin="$BLOCK_BEGIN" -v end="$BLOCK_END" '
		index($0, begin) == 1 && !inblock { inblock = 1; held = $0; next }
		inblock { held = held "\n" $0; if ($0 == end) { inblock = 0; held = "" } next }
		{ print }
		END { if (inblock) print held }
	' "$1"
}

drop_trailing_blank_lines() {
	awk '{ line[NR] = $0 } END { n = NR; while (n > 0 && line[n] ~ /^[ \t]*$/) n--; for (i = 1; i <= n; i++) print line[i] }' "$1"
}

# The rotation isn't in this block any more: Sunroom Screen applies it when it starts (and touch
# follows, labwc-rule.py --rotate).
labwc_block() {
	render "$SRC_DIR/files/labwc/autostart-block"
}

# labwc runs ~/.config/labwc/autostart with sh at login; Raspberry Pi OS starts labwc with
# --merge-config, so this file runs in addition to /etc/xdg/labwc/autostart.
write_labwc_autostart() {
	local file="$LABWC_DIR/autostart" base="$TMP_DIR/autostart.base" new="$TMP_DIR/autostart.new"
	mkdir -p "$LABWC_DIR"
	if [[ -f $file ]]; then
		strip_block "$file" >"$base"
	else
		: >"$base"
		LABWC_AUTOSTART_CREATED=1
	fi
	drop_trailing_blank_lines "$base" >"$new"
	if [[ -s $new ]]; then
		printf '\n' >>"$new"
	fi
	labwc_block >>"$new"
	if [[ -f $file ]] && cmp -s "$new" "$file"; then
		note "The desktop already starts the screen."
		return 0
	fi
	if [[ -f $file ]]; then
		cat "$new" >"$file"
	else
		install -m 0644 "$new" "$file"
	fi
	note "The desktop now starts the screen at login ($(tidy "$file"))."
}

remove_labwc_block() {
	local file="$LABWC_DIR/autostart"
	if [[ -f $file ]] && grep -q "^$BLOCK_BEGIN" "$file"; then
		strip_block "$file" >"$TMP_DIR/autostart.stripped"
		cat "$TMP_DIR/autostart.stripped" >"$file"
	fi
}

# raspi-config's do_blanking only edits the labwc autostart when labwc is running; on a
# labwc desktop, blanking is the swayidle line it adds there, so remove it ourselves too.
remove_swayidle() {
	local file="$LABWC_DIR/autostart"
	if [[ -f $file ]] && grep -q swayidle "$file"; then
		sed '/swayidle/d' "$file" >"$TMP_DIR/autostart.noidle"
		cat "$TMP_DIR/autostart.noidle" >"$file"
		note "Turned off the desktop's screen blanking (swayidle) in $(tidy "$file")."
	fi
}

# Unverified on hardware: that the Pi's X11 session (lxsession: rpd-x on Trixie, LXDE-pi-x
# on Bookworm) runs ~/.config/autostart entries, as XDG autostart says it should.
write_xdg_autostart() {
	install_template "$SRC_DIR/files/xdg/sunroom-kiosk.desktop" "$XDG_AUTOSTART_FILE" 0644
	note "The desktop now starts the screen at login ($(tidy "$XDG_AUTOSTART_FILE"))."
}

apply_labwc_settings() {
	local status=0
	python3 "$SHARE_DIR/labwc-rule.py" --installer-version "$KIOSK_VERSION" --rotate "$ROTATE" --output "$OUTPUT" 2>&1 |
		sed 's/^/    /' || status=$?
	if ((status != 0 && status != 2)); then
		warn "couldn't adjust the pointer and touch settings (labwc rc.xml); the screen still works."
	fi
	pkill -HUP -u "$(id -u)" -x labwc 2>/dev/null || true # reload labwc's settings if it is running
}

write_wifi_dropin() {
	if [[ ! -d /etc/NetworkManager/conf.d ]]; then
		note "This Pi doesn't use NetworkManager; leaving Wi-Fi power saving as it is."
		return 0
	fi
	{
		header_comment
		render "$SRC_DIR/files/NetworkManager/zz-sunroom-kiosk-wifi.conf"
	} >"$TMP_DIR/wifi.conf"
	NM_DROPIN_WRITTEN=$NM_DROPIN
	if sudo cmp -s "$TMP_DIR/wifi.conf" "$NM_DROPIN"; then
		note "Wi-Fi power saving is already off."
		return 0
	fi
	sudo install -m 0644 -o root -g root "$TMP_DIR/wifi.conf" "$NM_DROPIN"
	note "Turned off Wi-Fi power saving (it drops live updates)."
}

# Unverified: that every Raspberry Pi OS image ships systemd-time-wait-sync (it comes with
# systemd-timesyncd, which Raspberry Pi OS uses); it is checked for before enabling.
enable_time_wait_sync() {
	if ! systemctl cat systemd-time-wait-sync.service >/dev/null 2>&1; then
		note "systemd-time-wait-sync isn't available here; the screen waits for the clock by itself."
		return 0
	fi
	if systemctl is-enabled --quiet systemd-time-wait-sync.service 2>/dev/null; then
		return 0
	fi
	sudo systemctl enable systemd-time-wait-sync.service >/dev/null 2>&1 ||
		{
			warn "couldn't turn on systemd-time-wait-sync; the screen still waits for the clock itself."
			return 0
		}
	TIME_WAIT_SYNC_BY_US=1
	note "At startup, the Pi now sets its clock from the internet before relying on it."
}

# Where the firmware reads the kernel command line from, as raspi-config (Trixie) works it out.
cmdline_path() {
	local firmware=/boot/firmware prefix="" name=""
	[[ -e $firmware/config.txt ]] || firmware=/boot
	if [[ -r /proc/device-tree/chosen/os_prefix ]]; then
		prefix=$(tr -d '\0' </proc/device-tree/chosen/os_prefix)
	fi
	if command -v vcgencmd >/dev/null 2>&1; then
		name=$(vcgencmd get_config cmdline 2>/dev/null | sed -n 's/^cmdline=//p' || true)
	fi
	printf '%s/%s%s' "$firmware" "$prefix" "${name:-cmdline.txt}"
}

add_cmdline_key() {
	local key
	local -a keys=()
	read -ra keys <<<"$CMDLINE_KEYS"
	for key in "${keys[@]}"; do
		if [[ $key == "$1" ]]; then
			return 0
		fi
	done
	CMDLINE_KEYS="${CMDLINE_KEYS:+$CMDLINE_KEYS }$1"
}

# --force-hdmi: video=<output>:<mode>M@60D forces the mode and keeps the output on, and
# vc4.force_hotplug (a bit mask: 1 = HDMI0, 2 = HDMI1) ignores a monitor that is off at
# boot. The file is one line; tokens are replaced, never duplicated, and the first-ever
# original is kept as <file>.sunroom-backup so kiosk/uninstall.sh can restore them.
apply_force_hdmi() {
	local output=HDMI-A-1 bit file line backup video token new_line hotplug_old placed_video=0 placed_hotplug=0
	local -a tokens new_tokens=()
	if ((OUTPUT_GIVEN)) || [[ $OUTPUT == HDMI-A-[12] ]]; then
		output=$OUTPUT
	fi
	case $output in
	HDMI-A-1) bit=1 ;;
	HDMI-A-2) bit=2 ;;
	*)
		warn "--force-hdmi only works for HDMI screens (HDMI-A-1 or HDMI-A-2), not $output; skipped."
		return 0
		;;
	esac
	file=$(cmdline_path)
	if ! sudo test -f "$file"; then
		warn "couldn't find $file, so --force-hdmi was skipped."
		return 0
	fi
	line=$(sudo cat "$file")
	if [[ -z $line || $line == *$'\n'* || $line != *root=* ]]; then
		warn "$file doesn't look like the usual single line, so it was left alone (--force-hdmi skipped)."
		return 0
	fi
	backup="$file.sunroom-backup"
	if ! sudo test -e "$backup"; then
		sudo cp -p "$file" "$backup"
	fi
	video="video=$output:${FORCE_HDMI}M@60D"
	read -ra tokens <<<"$line"
	for token in "${tokens[@]}"; do
		case $token in
		"video=$output:"*)
			if ((!placed_video)); then
				new_tokens+=("$video")
				placed_video=1
			fi
			;;
		vc4.force_hotplug=*)
			if ((!placed_hotplug)); then
				hotplug_old=${token#*=}
				[[ $hotplug_old =~ ^[0-9]+$ ]] || hotplug_old=0
				new_tokens+=("vc4.force_hotplug=$((hotplug_old | bit))")
				placed_hotplug=1
			fi
			;;
		*) new_tokens+=("$token") ;;
		esac
	done
	if ((!placed_video)); then
		new_tokens+=("$video")
	fi
	if ((!placed_hotplug)); then
		new_tokens+=("vc4.force_hotplug=$bit")
	fi
	new_line="${new_tokens[*]}"
	CMDLINE_FILE=$file
	CMDLINE_BACKUP=$backup
	add_cmdline_key "video=$output:"
	add_cmdline_key "vc4.force_hotplug="
	if [[ $new_line == "$line" ]]; then
		note "The screen is already forced to $FORCE_HDMI on $output."
		return 0
	fi
	printf '%s\n' "$new_line" >"$TMP_DIR/cmdline.txt"
	sudo cp "$TMP_DIR/cmdline.txt" "$file"
	sync
	note "The Pi now always drives $output at $FORCE_HDMI, even if the screen is off at startup ($file)."
}

# ---------------------------------------------------------------------------- the screen helper

# The first backlight under /sys/class/backlight: DSI panels such as the Touch Display have
# one, HDMI monitors don't.
backlight_device() {
	local device
	for device in /sys/class/backlight/*; do
		if [[ -e $device/brightness ]]; then
			printf '%s' "${device##*/}"
			return 0
		fi
	done
	return 1
}

# ddcutil: for --brightness ddc, and for auto when the screen has no backlight of its own.
wants_ddc() {
	[[ $SCREEN_HELPER == yes ]] || return 1
	case $BRIGHTNESS in
	ddc) return 0 ;;
	auto) ! backlight_device >/dev/null ;;
	*) return 1 ;;
	esac
}

# add_to_group GROUP, when it exists and this user isn't in it yet. It counts from the next
# login, which the restart at the end brings. (The Pi's first user is usually in video and
# i2c already.)
add_to_group() {
	local group=$1 user
	user=$(id -un)
	getent group "$group" >/dev/null 2>&1 || return 0
	if [[ " $(id -nG "$user") " != *" $group "* ]]; then
		sudo usermod -aG "$group" "$user"
		note "Added $user to the $group group (it counts from the next restart)."
	fi
}

# A panel with a backlight (the Touch Display): the video group may write its brightness and
# bl_power, so the helper needs no sudo. udev runs the rule as each backlight appears; the
# trigger runs it now.
setup_backlight() {
	local rule="$TMP_DIR/backlight.rules"
	{
		header_comment
		render "$SRC_DIR/files/udev/90-sunroom-kiosk-backlight.rules"
	} >"$rule"
	BACKLIGHT_RULE_WRITTEN=$BACKLIGHT_RULE
	if ! sudo cmp -s "$rule" "$BACKLIGHT_RULE"; then
		sudo install -m 0644 -o root -g root "$rule" "$BACKLIGHT_RULE"
		sudo udevadm control --reload >/dev/null 2>&1 || true
	fi
	sudo udevadm trigger --action=add --subsystem-match=backlight >/dev/null 2>&1 || true
	add_to_group video
	if BACKLIGHT=$(backlight_device); then
		note "The screen helper dims the screen with its backlight ($BACKLIGHT)."
	else
		BACKLIGHT=""
		warn "this Pi has no screen backlight right now (/sys/class/backlight is empty)."
		note "The screen helper looks again each time it starts; until it finds one, the page dims itself."
	fi
}

# A monitor with DDC/CI takes brightness commands over the HDMI cable. ddcutil reaches it
# through /dev/i2c-N, which needs the i2c-dev module (loaded now and at every start) and the
# i2c group. The bus is found once, here, and saved for the helper.
setup_ddc() {
	local conf="$TMP_DIR/i2c.conf" detected
	if ! command -v ddcutil >/dev/null 2>&1; then
		note "Without ddcutil the screen helper can't set the brightness; the page dims itself."
		return 0
	fi
	{
		header_comment
		render "$SRC_DIR/files/modules-load/sunroom-kiosk-i2c.conf"
	} >"$conf"
	I2C_MODULES_WRITTEN=$I2C_MODULES_FILE
	if ! sudo cmp -s "$conf" "$I2C_MODULES_FILE"; then
		sudo install -m 0644 -o root -g root "$conf" "$I2C_MODULES_FILE"
	fi
	sudo modprobe i2c-dev >/dev/null 2>&1 || true
	add_to_group i2c
	note "Asking the screen whether it takes brightness commands (DDC/CI); this takes a few seconds..."
	detected=$(sudo ddcutil detect --brief 2>&1 || true)
	printf '%s\n' "$detected" >>"$LOG_FILE"
	DDC_BUS=$("$BIN_DIR/sunroom-kiosk" screen --ddc-bus "$OUTPUT" <<<"$detected" 2>>"$LOG_FILE" || true)
	if [[ $DDC_BUS =~ ^[0-9]+$ ]]; then
		note "The screen helper dims the screen over HDMI (DDC/CI, I2C bus $DDC_BUS)."
	else
		DDC_BUS=""
		note "The screen doesn't take brightness commands (DDC/CI), so the page dims itself in the evening."
		note "Many monitors have DDC/CI switched off in their own menu: turn it on there, then run the installer again."
	fi
}

# How the screen helper sets the brightness (--brightness), worked out here and saved in the
# screen's settings; the helper checks it again each time it starts.
setup_brightness() {
	DDC_BUS=""
	BACKLIGHT=""
	[[ $SCREEN_HELPER == yes ]] || return 0
	case $BRIGHTNESS in
	none) note "The screen helper leaves the brightness alone (--brightness none); the page dims itself." ;;
	sysfs) setup_backlight ;;
	ddc) setup_ddc ;;
	auto)
		if backlight_device >/dev/null; then
			setup_backlight
		else
			setup_ddc
		fi
		;;
	esac
}

setup_kiosk() {
	if ((SWITCH_TO_X11)); then
		note "Switching the desktop to X11, as asked..."
		sudo raspi-config nonint do_wayland W1 || die "Couldn't switch the desktop to X11." \
			"Run the installer without --x11 to keep the standard labwc desktop."
	fi
	sudo raspi-config nonint do_boot_behaviour B4 || die "Couldn't set the Pi to log in to the desktop by itself." \
		"Set it in Raspberry Pi Configuration (System: Auto login), then run the installer again."
	note "The Pi now starts the desktop and logs in by itself."
	if sudo raspi-config nonint do_blanking 1; then
		note "Screen blanking is off."
	else
		warn "couldn't turn off screen blanking; turn it off in Raspberry Pi Configuration (Display)."
	fi
	if [[ $SESSION == wayland ]]; then
		remove_swayidle
	fi
	install_agent
	install_root_helper
	setup_brightness
	write_kiosk_config
	install_units
	if [[ $SESSION == wayland ]]; then
		write_labwc_autostart
		rm -f "$XDG_AUTOSTART_FILE"
		apply_labwc_settings
	else
		write_xdg_autostart
		remove_labwc_block
	fi
	write_wifi_dropin
	enable_time_wait_sync
	if [[ -n $FORCE_HDMI ]]; then
		apply_force_hdmi
	fi
	if [[ $ROTATE != 0 ]]; then
		note "The picture on $OUTPUT will be turned $ROTATE degrees, and touch with it."
		note "To change it later: Settings → This Screen → Rotation, on the screen."
	fi
	if [[ $SCREEN_HELPER == yes ]]; then
		note "Set the screen's sleep times in Sunroom: Settings → Display → Sleep."
	else
		note "No screen helper (--no-screen-helper): at night the page goes black or dim, and the screen itself stays on." \
			"Set the times in Sunroom: Settings → Display → Sleep."
	fi
}

# ---------------------------------------------------------------------------- step 5: summary

show_qr() {
	if command -v qrencode >/dev/null 2>&1; then
		say ""
		qrencode -t ANSIUTF8 -m 2 "$1" || true
	fi
}

on_sd_card() {
	[[ $(findmnt -no SOURCE / 2>/dev/null || true) == /dev/mmcblk* ]]
}

summary() {
	local host ip phone
	say ""
	case $MODE in
	display)
		if [[ -n $URL ]]; then
			say "The screen is set up. It will show Sunroom from $URL"
		else
			say "The screen is set up. When it starts, it looks for Sunroom on your network:"
			say "pick yours there, or type the address you open on your other devices."
			if [[ $PLATFORM == pi ]]; then
				say "No Sunroom yet? Run the installer again with --with-sunroom to put it on this Pi too."
			fi
		fi
		say ""
		say "Next:"
		if [[ $PLATFORM == pi ]]; then
			say "  1. After the restart, the screen shows a six-character code."
		else
			say "  1. When it starts, the screen shows a six-character code."
		fi
		say "  2. On a device signed in to Sunroom, open Settings → Devices → Pair a Display"
		say "     (under More on a phone) and type that code."
		if [[ -n $URL ]]; then
			say ""
			say "Your other devices use the same address: $URL"
			say "If the screen says it can't reach Sunroom, check that this address opens on another device."
			show_qr "$URL"
		fi
		;;
	all | server)
		host=$(pi_hostname)
		ip=$(pi_ip)
		phone="http://$host.local:$PORT"
		say "Sunroom is running on this Pi."
		say ""
		say "On a phone or computer, open:   $phone"
		if [[ -n $ip ]]; then
			say "If that doesn't open:           http://$ip:$PORT"
			say "(A device on a VPN, or a phone on mobile data, can't see .local names; use the second address.)"
		fi
		show_qr "$phone"
		say ""
		say "Next:"
		say "  1. Open that address on a phone or computer and follow the setup."
		if [[ $MODE == all ]]; then
			say "  2. After the restart, the screen shows a six-character code."
			say "     Type it on a signed-in device: Settings → Devices → Pair a Display (under More"
			say "     on a phone)."
		fi
		say ""
		say "Update Sunroom later with:  sudo /opt/sunroom/update.sh"
		if on_sd_card; then
			say "Tip: Sunroom keeps your family's calendar on this Pi's memory card. A good card (A2) or a"
			say "USB SSD and the official power supply keep it safe; Sunroom also backs up every night."
		fi
		;;
	esac
	if [[ $MODE == server ]]; then
		say "Remove Sunroom and its data with:  bash ~/.local/share/sunroom-kiosk/uninstall.sh --purge"
	else
		say "Remove the Sunroom screen setup with:  bash ~/.local/share/sunroom-kiosk/uninstall.sh"
	fi
	say "This install's log:  $(tidy "$LOG_FILE")"
}

offer_reboot() {
	say ""
	if ((NO_REBOOT)); then
		say "Restart the Pi when you're ready (sudo reboot)."
		return 0
	fi
	if [[ $MODE == server ]]; then
		say "A restart is optional; it checks that Sunroom comes back by itself."
	else
		say "A restart starts the screen."
	fi
	if ask_yes_no "Reboot now?" y n; then
		say "Restarting now. Give it a minute or two."
		sleep 2
		sudo systemctl reboot
	else
		say "OK. Restart later with: sudo reboot"
	fi
}

# ---------------------------------------------------------------------------- uninstall

run_uninstall() {
	local script="" dir status=0
	VERSION=${VERSION#v}
	if [[ -n $SCRIPT_PATH && -f $SCRIPT_PATH ]]; then
		dir=$(cd "$(dirname "$SCRIPT_PATH")" && pwd)
		if [[ -f $dir/uninstall.sh ]]; then
			script="$dir/uninstall.sh"
		fi
	fi
	if [[ -z $script && -f $SHARE_DIR/uninstall.sh ]]; then
		script="$SHARE_DIR/uninstall.sh"
	fi
	if [[ -z $script ]]; then
		TMP_DIR=$(mktemp -d)
		trap cleanup EXIT
		download_kiosk_files
		script="$SRC_DIR/uninstall.sh"
	fi
	bash "$script" "${UNINSTALL_ARGS[@]}" || status=$?
	exit "$status"
}

# ---------------------------------------------------------------------------- another Linux computer

# A browser command here that Sunroom Screen can use. A snap's can't open the profile under
# ~/.config or read the policy in /etc, so it doesn't count: Ubuntu's Chromium is one, and its
# /usr/bin/chromium-browser is a script that runs the snap. browser.py skips them the same way.
usable_browser() {
	local path start
	path=$(command -v "$1" 2>/dev/null) || return 1
	if [[ $path == /snap/* || $(readlink -f "$path" 2>/dev/null || true) == /snap/* ]]; then
		return 1
	fi
	start=$(head -c 4096 "$path" 2>/dev/null | tr -d '\0' || true)
	[[ $start != '#!'*/snap/* ]]
}

# Chromium, Google Chrome or Microsoft Edge: the names Sunroom Screen looks for (browser.py).
linux_browser() {
	local name
	for name in chromium chromium-browser google-chrome google-chrome-stable microsoft-edge microsoft-edge-stable; do
		if usable_browser "$name"; then
			printf '%s' "$name"
			return 0
		fi
	done
	return 1
}

# The policy folders of the browsers installed here (policy.py's LINUX_DIRS).
linux_policy_dirs() {
	if usable_browser chromium || usable_browser chromium-browser; then
		printf '%s\n' /etc/chromium/policies/managed
	fi
	if usable_browser google-chrome || usable_browser google-chrome-stable; then
		printf '%s\n' /etc/opt/chrome/policies/managed
	fi
	if usable_browser microsoft-edge || usable_browser microsoft-edge-stable; then
		printf '%s\n' /etc/opt/edge/policies/managed
	fi
}

# Which browser comes when there's none: the system's own Chromium where its package is the
# browser itself (Debian, Fedora, openSUSE, Arch), else Google Chrome from Google (Ubuntu, whose
# Chromium is a snap). Empty when the installer doesn't know this system's packages.
linux_browser_plan() {
	if command -v apt-get >/dev/null 2>&1; then
		if pkg_available chromium; then
			printf 'Chromium, with apt'
		else
			printf 'Google Chrome, from Google (apt has no Chromium of its own here; Ubuntu'"'"'s is a snap)'
		fi
	elif command -v dnf >/dev/null 2>&1; then
		printf 'Chromium, with dnf (or Google Chrome, from Google, when dnf has none)'
	elif command -v zypper >/dev/null 2>&1; then
		printf 'Chromium, with zypper'
	elif command -v pacman >/dev/null 2>&1; then
		printf 'Chromium, with pacman'
	fi
}

# Google Chrome's own package, for this computer's processor (64-bit Intel or ARM). Installing it
# adds Google's software source, so the system keeps Chrome up to date with everything else.
install_google_chrome() {
	local kind=$1 arch file
	if [[ $kind == deb ]]; then
		arch=$(dpkg --print-architecture 2>/dev/null || uname -m)
	else
		arch=$(uname -m)
	fi
	case $kind:$arch in
	deb:amd64 | deb:arm64 | rpm:x86_64 | rpm:aarch64) ;;
	*)
		die "There's no Chromium to install here, and Google Chrome isn't made for this computer ($arch)." \
			"Install Chromium, Google Chrome or Microsoft Edge yourself, then run this again."
		;;
	esac
	file="google-chrome-stable_current_$arch.$kind"
	note "Downloading Google Chrome from Google..."
	curl -fsSL --retry 3 --connect-timeout 15 -o "$TMP_DIR/$file" "$CHROME_LINUX_BASE/$file" 2>>"$LOG_FILE" ||
		die "Couldn't download Google Chrome. Check the internet connection, then run this again."
	note "Installing Google Chrome (this takes a few minutes)..."
	if [[ $kind == deb ]]; then
		wait_for_apt
		quietly apt_get install -y "$TMP_DIR/$file" ||
			die "Couldn't install Google Chrome; its last messages are above. Running the installer again is safe."
	else
		quietly sudo dnf install -y "$TMP_DIR/$file" ||
			die "Couldn't install Google Chrome; its last messages are above. Running the installer again is safe."
	fi
}

# A browser for the screen when this computer has none it can use (linux_browser_plan says which).
install_linux_browser() {
	start_sudo
	if command -v apt-get >/dev/null 2>&1; then
		wait_for_apt
		note "Refreshing the list of available software..."
		quietly apt_get update || die "Couldn't refresh the list of available software." \
			"Check the internet connection and that the date and time are right (type: date), then run this again."
		if pkg_available chromium; then
			note "Installing Chromium (this takes a few minutes)..."
			quietly apt_get install -y chromium ||
				die "Couldn't install Chromium; its last messages are above. Running the installer again is safe."
		else
			install_google_chrome deb
		fi
	elif command -v dnf >/dev/null 2>&1; then
		note "Installing Chromium (this takes a few minutes)..."
		if ! quietly sudo dnf install -y chromium; then
			note "There's no Chromium to install here, so Google Chrome it is."
			install_google_chrome rpm
		fi
	elif command -v zypper >/dev/null 2>&1; then
		note "Installing Chromium (this takes a few minutes)..."
		quietly sudo zypper --non-interactive install chromium ||
			die "Couldn't install Chromium; its last messages are above." "Install it yourself, then run this again."
	elif command -v pacman >/dev/null 2>&1; then
		note "Installing Chromium (this takes a few minutes)..."
		quietly sudo pacman -S --needed --noconfirm chromium ||
			die "Couldn't install Chromium; its last messages are above." \
				"Install it yourself (sudo pacman -Syu chromium), then run this again."
	else
		die "Sunroom Screen needs Chromium, Google Chrome or Microsoft Edge, and none is installed." \
			"The installer doesn't know how to install software here: install Chromium, then run this again."
	fi
	BROWSER=$(linux_browser) || die "The browser was installed, but the installer can't find it." \
		"Open a new terminal and run the installer again."
	note "The browser: $BROWSER."
}

os_name() {
	# shellcheck source=/dev/null
	(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-}") || true
}

check_linux() {
	local name
	command -v curl >/dev/null 2>&1 || die "The installer needs curl, which isn't installed." \
		"Install it (for example: sudo apt install curl), then run this again."
	if ! command -v systemctl >/dev/null 2>&1 || ! user_systemctl show-environment >/dev/null 2>&1; then
		die "Sunroom Screen needs systemd's user services, which this computer doesn't have." \
			"Put the screen on a Raspberry Pi instead (docs/KIOSK.md)."
	fi
	name=$(os_name)
	if BROWSER=$(linux_browser); then
		note "${name:-Linux} ($(uname -m)); the browser: $BROWSER."
	else
		BROWSER=""
		note "${name:-Linux} ($(uname -m)); no browser the screen can use yet, so it installs one."
	fi
	case ${XDG_SESSION_TYPE:-} in
	wayland | x11) SESSION=$XDG_SESSION_TYPE ;;
	*) SESSION="" ;; # Sunroom Screen works it out when the desktop starts it
	esac
}

# The browser's policy (policy.py): quiet, and the Sunroom page may reach Sunroom Screen here
# without asking (Chrome's Local Network Access), whichever Sunroom the screen shows, so it is
# right from the browser's first start (ADR 0042). It's root's to write, so sudo is asked for it
# and for the root helper that lets Sunroom Screen write it again as it starts (ADR 0038).
# Without sudo the browser asks once, on the screen.
write_linux_policy() {
	local tmp="$TMP_DIR/policy.json" dir dirs wrote=0
	dirs=$(linux_policy_dirs)
	[[ -n $dirs ]] || return 0
	if ! "$BIN_DIR/sunroom-kiosk" policy >"$tmp" 2>>"$LOG_FILE"; then
		warn "couldn't make the browser's settings; the browser asks once, on the screen, instead."
		return 0
	fi
	note "Setting up the browser needs sudo, so it may ask for your password."
	if ! sudo -v; then
		warn "without sudo the browser may ask once, on the screen, to reach Sunroom Screen."
		return 0
	fi
	if [[ -x /usr/bin/python3 ]]; then
		install_root_helper
	else
		warn "there's no /usr/bin/python3 for Sunroom Screen's root helper, so the browser may ask once, on the screen."
	fi
	for dir in $dirs; do
		if sudo install -d -m 0755 "$dir" && sudo install -m 0644 -o root -g root "$tmp" "$dir/sunroom-kiosk.json"; then
			wrote=1
		else
			warn "couldn't write $dir/sunroom-kiosk.json; the browser may ask once, on the screen."
		fi
	done
	if ((wrote)); then
		note "The browser won't ask for sign-in, passwords or translations, and Sunroom may reach Sunroom Screen."
	fi
}

# Start Sunroom Screen now when this computer's desktop is signed in: the one this runs on,
# or the one systemd's user manager knows (the desktop fills in its address at sign-in, so this
# works over ssh too). Else it starts at the next sign-in.
start_screen() {
	local environment
	say ""
	if user_systemctl is-active --quiet sunroom-kiosk.service; then
		say "Sunroom Screen is running, on this version."
		return 0
	fi
	if [[ -n ${WAYLAND_DISPLAY:-}${DISPLAY:-} ]]; then
		user_systemctl import-environment WAYLAND_DISPLAY DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE >/dev/null 2>&1 || true
	fi
	environment=$'\n'$(user_systemctl show-environment 2>/dev/null || true)
	if [[ $environment != *$'\n'WAYLAND_DISPLAY=* && $environment != *$'\n'DISPLAY=* ]]; then
		say "Sunroom Screen starts the next time you sign in to this computer's desktop."
		return 0
	fi
	if ! user_systemctl --no-block restart sunroom-kiosk.service; then
		warn "Sunroom Screen didn't start just now (journalctl --user -u sunroom-kiosk says why); it starts at the next sign-in."
		return 0
	fi
	say "Starting Sunroom Screen now; it fills the whole screen."
	say "To close it: Settings → This Screen → Quit Sunroom Screen, on the screen, or in a terminal:"
	say "  systemctl --user stop sunroom-kiosk   (either way, it starts again at the next sign-in)"
}

# ---------------------------------------------------------------------------- a Mac

# Google Chrome, Chromium or Microsoft Edge in /Applications or ~/Applications: where Sunroom
# Screen looks for them (browser.py).
mac_browser() {
	local app dir
	for app in "Google Chrome" "Chromium" "Microsoft Edge"; do
		for dir in /Applications "$HOME/Applications"; do
			if [[ -d "$dir/$app.app" ]]; then
				printf '%s' "$app"
				return 0
			fi
		done
	done
	return 1
}

# Where Google Chrome goes when the installer brings it: /Applications when this account may write
# there (an administrator's may, with no password), else ~/Applications.
mac_apps_dir() {
	if [[ -w /Applications ]]; then
		printf '/Applications'
	else
		printf '%s/Applications' "$HOME"
	fi
}

check_macos() {
	local system
	system="macOS $(sw_vers -productVersion 2>/dev/null || true) ($(uname -m))"
	if BROWSER=$(mac_browser); then
		note "$system; the browser: $BROWSER."
	else
		BROWSER=""
		note "$system; no browser the screen can use yet, so it installs Google Chrome."
	fi
	SESSION=""
}

# Google Chrome from Google's disk image. The copy is made without extended attributes (the image's
# empty Finder information would fail the strict check) and checked for Google's own signature
# before it goes into Applications.
install_chrome_mac() {
	local dmg="$TMP_DIR/googlechrome.dmg" mount="$TMP_DIR/googlechrome" staged="$TMP_DIR/staged" dest
	dest=$(mac_apps_dir)
	note "Downloading Google Chrome from Google..."
	curl -fsSL --retry 3 --connect-timeout 15 -o "$dmg" "$CHROME_MAC_DMG" 2>>"$LOG_FILE" ||
		die "Couldn't download Google Chrome. Check the internet connection, then run this again."
	mkdir -p "$mount" "$staged"
	quietly hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$mount" "$dmg" ||
		die "Couldn't open Google Chrome's download; it may be damaged. Run the installer again."
	MOUNTED_DMG=$mount
	ditto --noextattr --norsrc "$mount/Google Chrome.app" "$staged/Google Chrome.app" 2>>"$LOG_FILE" ||
		die "Couldn't copy Google Chrome out of its download. Running the installer again is safe."
	hdiutil detach "$mount" -quiet 2>>"$LOG_FILE" || true
	MOUNTED_DMG=""
	if ! codesign --verify --deep --strict -R="$CHROME_MAC_REQUIREMENT" "$staged/Google Chrome.app" 2>>"$LOG_FILE"; then
		die "The Google Chrome download isn't signed by Google, so it wasn't installed." \
			"Run the installer again; if it happens again, install Google Chrome from google.com/chrome, then run this again."
	fi
	mkdir -p "$dest"
	mv "$staged/Google Chrome.app" "$dest/" ||
		die "Couldn't put Google Chrome in $(tidy "$dest"). Running the installer again is safe."
	BROWSER="Google Chrome"
	note "Installed Google Chrome in $(tidy "$dest"), checked for Google's signature."
}

launch_agent_loaded() {
	launchctl print "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1
}

# The LaunchAgent starts Sunroom Screen at sign-in, and again if it fails (not after Quit). One
# that was running is started again at once, on this version.
install_launch_agent() {
	local plist="$TMP_DIR/launch-agent.plist" was_loaded=0
	render "$SRC_DIR/files/launchd/$LAUNCH_AGENT_LABEL.plist" >"$plist"
	plutil -lint "$plist" >/dev/null || die "Sunroom Screen's LaunchAgent didn't check out (plutil); nothing was changed."
	mkdir -p "$(dirname "$LAUNCH_AGENT")" "$HOME/Library/Logs"
	if launch_agent_loaded; then
		was_loaded=1
		launchctl bootout "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1 || true
	fi
	install -m 0644 "$plist" "$LAUNCH_AGENT"
	note "Sunroom Screen now starts when you sign in ($(tidy "$LAUNCH_AGENT"))."
	if ((was_loaded)); then
		launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT" ||
			die "Sunroom Screen didn't start again. Its log: ~/Library/Logs/sunroom-kiosk.log"
		LAUNCHED=1
	fi
}

# Start Sunroom Screen now when this Mac's desktop is signed in; else at the next sign-in.
start_screen_mac() {
	say ""
	if ((LAUNCHED)); then
		say "Sunroom Screen started again, on this version."
		return 0
	fi
	if ! launchctl print "gui/$(id -u)" >/dev/null 2>&1; then
		say "Sunroom Screen starts the next time you sign in to this Mac."
		return 0
	fi
	if ! launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT" 2>>"$LOG_FILE"; then
		warn "Sunroom Screen didn't start just now (~/Library/Logs/sunroom-kiosk.log says why); it starts at the next sign-in."
		return 0
	fi
	say "Starting Sunroom Screen now; it fills the whole screen."
	say "To close it: Settings → This Screen → Quit Sunroom Screen, on the screen, or in Terminal:"
	say "  launchctl bootout gui/$(id -u)/$LAUNCH_AGENT_LABEL   (either way, it starts again at the next sign-in)"
}

# ---------------------------------------------------------------------------- --dry-run

# What a real run would do here, from what it can see without changing anything: no sudo, no
# downloads, no files. CI runs it on Linux, macOS (bash 3.2) and Windows (Git Bash).
dry_run() {
	say "Sunroom installer $KIOSK_VERSION: a dry run. Nothing on this computer changes."
	say ""
	case $PLATFORM in
	pi | linux | macos) dry_run_screen ;;
	windows)
		say "This computer: Windows. A real run stops here: Windows has its own installer, in PowerShell:"
		say "  $WINDOWS_COMMAND"
		;;
	*) say "This computer runs $(uname -s), which this installer doesn't know, so a real run stops here." ;;
	esac
}

# The plan on a Pi, another Linux computer or a Mac, step by step as main runs them.
dry_run_screen() {
	local name model browser shows wheel="from GitHub, checked against its release's SHA256SUMS"
	name=$(os_name)
	if [[ $PLATFORM == pi ]]; then
		model=$({ tr -d '\0' </proc/device-tree/model; } 2>/dev/null || true)
		say "This computer: ${model:-a Raspberry Pi}, ${name:-an unknown system}."
	elif [[ $PLATFORM == macos ]]; then
		say "This computer: macOS $(sw_vers -productVersion 2>/dev/null || true) ($(uname -m))."
	else
		say "This computer: ${name:-Linux} ($(uname -m))."
	fi
	print_plan
	say ""
	say "A real run would:"
	if [[ $PLATFORM == pi ]]; then
		say "  - check for 64-bit Raspberry Pi OS (Bookworm or Trixie), 2 GB free and the internet"
		if [[ $MODE == server ]]; then
			say "  - install what it needs with apt, only what's missing (curl, jq and qrencode)"
		else
			say "  - install what it needs with apt, only what's missing (curl, jq, qrencode, python3,"
			say "    Chromium and the desktop's screen tools)"
		fi
	elif [[ $PLATFORM == macos ]]; then
		if browser=$(mac_browser); then
			say "  - check for the internet, and use $browser"
		else
			say "  - check for the internet, then download Google Chrome from Google, check Google's"
			say "    signature on it, and put it in $(tidy "$(mac_apps_dir)")"
		fi
	elif browser=$(linux_browser); then
		say "  - check for the internet, and use $browser"
	else
		browser=$(linux_browser_plan)
		if [[ -z $browser ]]; then
			say "  - stop: it needs Chromium, Google Chrome or Microsoft Edge, and doesn't know how to"
			say "    install software here"
			return 0
		fi
		say "  - check for the internet, then install a browser with sudo, as there's none it can use:"
		say "    $browser"
	fi
	if [[ -n $URL ]]; then
		say "  - check that Sunroom answers at $URL"
	fi
	if [[ $MODE != display ]]; then
		say "  - install Docker when it's missing, and run Sunroom ($SUNROOM_IMAGE:${VERSION:-latest}) from"
		say "    $SERVER_DIR on port $PORT"
		say "  - tell Sunroom screens on the network where it is ($AVAHI_SERVICE)"
	fi
	if [[ $MODE == server ]]; then
		say "  - offer to restart"
		return 0
	fi
	if [[ -n $AGENT_WHEEL ]]; then
		wheel="from $AGENT_WHEEL"
	fi
	say "  - install uv $UV_VERSION in $(tidy "$BIN_DIR") when there's no uv, and with it Sunroom Screen"
	say "    $KIOSK_VERSION ($wheel)"
	if [[ -n $SERVER_WHEEL ]]; then
		say "  - keep Sunroom's own wheel from $SERVER_WHEEL for On This Computer"
	fi
	if [[ $PLATFORM == pi ]]; then
		say "  - let Sunroom Screen update this Pi and set the browser's policy through one root helper"
		say "    ($ROOT_HELPER, allowed by $SUDOERS_FILE)"
	fi
	case $MODE in
	all) shows="http://localhost:$PORT" ;;
	*) shows=${URL:-the Sunroom it finds on the network (or an address typed on it)} ;;
	esac
	say "  - save the screen's settings in $(tidy "$CONFIG_DIR/config"), where it shows"
	say "    $shows"
	if [[ $PLATFORM == pi ]]; then
		say "  - log in to the desktop by itself, turn off screen blanking and Wi-Fi power saving,"
		say "    wait for the clock at startup, and start Sunroom Screen with the desktop"
		say "    (sunroom-kiosk.service)"
		if [[ $ROTATE != 0 ]]; then
			say "  - turn the picture ${ROTATE} degrees, and touch with it"
		fi
		if [[ -n $FORCE_HDMI ]]; then
			say "  - always drive the screen at $FORCE_HDMI"
		fi
		if ((NO_REBOOT)); then
			say "  - leave the restart to you (--no-reboot)"
		else
			say "  - offer to restart"
		fi
	elif [[ $PLATFORM == macos ]]; then
		say "  - start Sunroom Screen when you sign in (a LaunchAgent,"
		say "    $(tidy "$LAUNCH_AGENT"))"
		say "  - start Sunroom Screen now when this Mac's desktop is signed in (it fills the screen)"
		say "Nothing else is installed, nothing needs an administrator, and no other settings change."
	else
		say "  - start Sunroom Screen when you sign in ($(tidy "$XDG_AUTOSTART_FILE"),"
		say "    sunroom-kiosk.service)"
		say "  - set the browser's policy with sudo, and let Sunroom Screen keep it in step with the"
		say "    address it shows through one root helper ($ROOT_HELPER, allowed by"
		say "    $SUDOERS_FILE)"
		say "  - start Sunroom Screen now when this computer's desktop is signed in (it fills"
		say "    the screen)"
		say "Nothing else is installed, and no other settings on this computer change."
	fi
}

# ---------------------------------------------------------------------------- main

print_plan() {
	local shows
	if [[ -n $URL ]]; then
		shows=", showing Sunroom from $URL"
	else
		shows="; it finds Sunroom on your network by itself"
	fi
	case $MODE in
	all) say "This sets up Sunroom and the screen on this Pi. It takes about 10 to 20 minutes." ;;
	display) say "This sets up a Sunroom screen on $MACHINE$shows. It takes a few minutes." ;;
	server) say "This sets up Sunroom on this Pi, without a screen. It takes about 10 minutes." ;;
	esac
	if ((KEPT_MODE)) && [[ $MODE == all ]]; then
		say "(This Pi runs Sunroom from an earlier install, so it keeps it. --display-only would set up"
		say "the screen alone.)"
	elif ((KEPT_MODE)); then
		say "(This Pi runs Sunroom without a screen from an earlier install, so it stays that way.)"
	fi
}

begin_run() {
	setup_logging
	trap 'on_error $? $LINENO' ERR
	trap cleanup EXIT
	TMP_DIR=$(mktemp -d)
	load_previous_state
	say "Sunroom installer $KIOSK_VERSION"
	print_plan
}

install_on_pi() {
	begin_run
	step "Checking this Pi" "checking this Pi"
	start_sudo
	check_platform
	check_disk
	check_internet
	if [[ $MODE == display && -n $URL ]]; then
		check_remote_server
	fi
	if [[ $MODE != server ]]; then
		detect_session
		resolve_output
	fi
	wait_for_apt
	get_kiosk_files

	step "Installing what it needs" "installing software"
	install_packages

	if [[ $MODE != display ]]; then
		step "Installing Docker" "installing Docker"
		install_docker
		step "Starting Sunroom" "starting Sunroom"
		write_stack
		start_stack
		write_avahi_service
	fi

	install_helper_copies
	if [[ $MODE != server ]]; then
		step "Setting up the screen" "setting up the screen"
		setup_kiosk
	fi
	save_state

	step "All done" "finishing"
	summary
	offer_reboot
}

# A Mac: Sunroom Screen alone, started at sign-in by a LaunchAgent, and Google Chrome when there's
# no browser. No administrator, no other settings; Sunroom Screen writes the browser's policy
# itself (defaults, as this user).
install_on_macos() {
	begin_run
	step "Checking this Mac" "checking this Mac"
	check_macos
	check_internet
	if [[ -n $URL ]]; then
		check_remote_server
	fi
	get_kiosk_files

	if [[ -z $BROWSER ]]; then
		step "Installing Google Chrome" "installing Google Chrome"
		install_chrome_mac
	fi

	step "Setting up the screen" "setting up the screen"
	install_helper_copies
	install_agent
	write_kiosk_config
	install_launch_agent
	save_state

	step "All done" "finishing"
	summary
	start_screen_mac
}

# Another Linux computer: Sunroom Screen alone, started at sign-in, and a browser when there's
# none. No other packages, no system settings; root only for the browser and its policy.
install_on_linux() {
	begin_run
	step "Checking this computer" "checking this computer"
	check_linux
	check_internet
	if [[ -n $URL ]]; then
		check_remote_server
	fi
	get_kiosk_files

	if [[ -z $BROWSER ]]; then
		step "Installing a browser" "installing a browser"
		install_linux_browser
	fi

	step "Setting up the screen" "setting up the screen"
	install_helper_copies
	install_agent
	write_kiosk_config
	install_units
	write_xdg_autostart
	write_linux_policy
	save_state

	step "All done" "finishing"
	summary
	start_screen
}

main() {
	ORIGINAL_ARGS=("$@")
	parse_args "$@"
	detect_platform
	refuse_root
	detect_tty
	if ((UNINSTALL)); then
		run_uninstall
	fi
	validate_args
	if ((DRY_RUN)); then
		dry_run
		exit 0
	fi
	case $PLATFORM in
	pi) install_on_pi ;;
	linux) install_on_linux ;;
	macos) install_on_macos ;;
	windows)
		die "This installer is for a Raspberry Pi and Linux. Windows has its own; in PowerShell, run:" \
			"  $WINDOWS_COMMAND"
		;;
	*)
		die "This installer works on a Raspberry Pi or another Linux computer; this one runs $(uname -s)."
		;;
	esac
}

main "$@"
