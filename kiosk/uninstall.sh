#!/usr/bin/env bash
# Sunroom uninstaller: takes off this Pi (or another Linux computer, or a Mac) what
# kiosk/install.sh set up for the screen.
#
#   bash uninstall.sh [--purge | --purge-local] [--yes] [--from-screen] [--dry-run]
#   (the same as: bash install.sh --uninstall [--purge] [--yes]; the installer keeps a copy
#    of this script at ~/.local/share/sunroom-kiosk/uninstall.sh)
#
# This Screen's Uninstall (ADR 0042) runs that copy as "--yes --from-screen [--purge-local]", in
# a process of its own once Sunroom Screen has quit: nobody is at a keyboard, so it asks nothing,
# and the files root owns go through Sunroom Screen's root helper ("remove-root-files", which
# sudoers allows without a password) or stay where there's no helper; the Pi's start-up settings
# (the kernel command line, systemd-time-wait-sync) need a terminal.
#
# Removes Sunroom Screen (it switches the screen back on as it stops; then uv uninstalls it,
# and its kept wheels go), its systemd user unit and the units of the screen helper and nightly
# restart from before 0.13.0, a Mac's LaunchAgent and the browser's preferences Sunroom Screen
# set there, its root helper and sudoers rule, the browser's policy files, its
# settings, the labwc autostart block or the XDG autostart entry, the labwc pointer and touch
# settings (putting back rc.xml.sunroom-backup when nothing else changed), the Wi-Fi
# power-saving drop-in, the backlight udev rule and i2c-dev module file, the kernel command line
# options it added, and systemd-time-wait-sync if the installer turned it on. It asks before
# deleting the browser profile, which holds the screen's pairing. Docker and Sunroom with its
# data stay unless you add --purge, which runs "docker compose down -v" in /opt/sunroom and
# deletes that folder; Sunroom run on this computer as a program (ADR 0038) stays too, with its
# data, unless --purge, which stops it, uninstalls it and deletes its data, after asking.
# uv, desktop autologin, "no screen blanking", installed packages
# (ddcutil, wlopm) and group memberships (video, i2c) are left as they are.
#
# Like the installer: run it as your normal user (it uses sudo itself), questions are read
# from the keyboard (/dev/tty), --yes answers yes to all of them, and nothing runs until
# the last line. See docs/PLAN.md §13.2.

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-}"
STATE_DIR="$HOME/.local/state/sunroom-kiosk"
LOG_FILE="$STATE_DIR/uninstall.log"
STATE_FILE="$STATE_DIR/install-state"
LABWC_STATE="$STATE_DIR/labwc-rule.json"
CONFIG_DIR="$HOME/.config/sunroom-kiosk"
SHARE_DIR="$HOME/.local/share/sunroom-kiosk"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
LABWC_DIR="$HOME/.config/labwc"
XDG_AUTOSTART_FILE="$HOME/.config/autostart/sunroom-kiosk.desktop"
LAUNCH_AGENT_LABEL="app.sunroom.kiosk"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"
SERVER_DIR="/opt/sunroom"
# Sunroom run on this computer as a program (agent local.py, ADR 0038).
LOCAL_UNIT="$UNIT_DIR/sunroom.service"
LOCAL_LAUNCH_AGENT_LABEL="app.sunroom.server"
LOCAL_LAUNCH_AGENT="$HOME/Library/LaunchAgents/$LOCAL_LAUNCH_AGENT_LABEL.plist"
LOCAL_STATE="$STATE_DIR/sunroom.json"
if [[ $(uname -s) == Darwin ]]; then
	LOCAL_DATA="$HOME/Library/Application Support/Sunroom"
else
	LOCAL_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/sunroom"
fi
AVAHI_SERVICE="/etc/avahi/services/sunroom.service"
NM_DROPIN="/etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf"
BACKLIGHT_RULE="/etc/udev/rules.d/90-sunroom-kiosk-backlight.rules"
I2C_MODULES_FILE="/etc/modules-load.d/sunroom-kiosk-i2c.conf"
ROOT_HELPER="/usr/local/sbin/sunroom-kiosk-root"
SUDOERS_FILE="/etc/sudoers.d/sunroom-kiosk"
# The browser's policy, which Sunroom Screen (or the installer) writes (agent policy.py).
POLICY_FILES=(/etc/chromium/policies/managed/sunroom-kiosk.json /etc/opt/chrome/policies/managed/sunroom-kiosk.json /etc/opt/edge/policies/managed/sunroom-kiosk.json)
BLOCK_BEGIN="# >>> sunroom-kiosk"
BLOCK_END="# <<< sunroom-kiosk <<<"
UNITS=(sunroom-kiosk.service sunroom-screen.service sunroom-kiosk-restart.service sunroom-kiosk-restart.timer)

PURGE=0
PURGE_LOCAL=0
FROM_SCREEN=0
DRY_RUN=0
YES=0
HAVE_TTY=0
TMP_DIR=""
SUDO_READY=0
NEEDS_RESTART=0

say() {
	printf '%s\n' "$*"
}

note() {
	printf '    %s\n' "$*"
}

warn() {
	printf '    Heads up: %s\n' "$*"
}

die() {
	printf '\n' >&2
	printf '%s\n' "$@" >&2
	exit 1
}

tidy() {
	local path=$1
	if [[ $path == "$HOME"/* ]]; then
		path="~${path#"$HOME"}"
	fi
	printf '%s' "$path"
}

usage() {
	cat <<'EOF'
Remove the Sunroom screen setup from this computer.

Usage: bash uninstall.sh [--purge | --purge-local] [--yes] [--from-screen] [--dry-run]

  --purge        Also stop Sunroom and delete it and ALL its data (calendars, lists, photos)
                 from this computer: docker compose down -v in /opt/sunroom, then that folder,
                 and Sunroom run here as a program, with its data folder.
  --purge-local  Only Sunroom run here as a program, with its data (never /opt/sunroom).
  --yes          Answer yes to every question, including deleting the screen's pairing.
  --from-screen  What This Screen's Uninstall runs: no questions (as --yes), and the files
                 root owns through Sunroom Screen's root helper, without sudo's password.
  --dry-run      Say what would be removed, and change nothing.
  --help         Show this help

Docker itself, uv, desktop autologin and "no screen blanking" are left as they are.
EOF
}

# ask_yes_no QUESTION DEFAULT(y|n): --yes answers yes; with no keyboard the answer is no.
ask_yes_no() {
	local question=$1 default=$2 hint answer
	if ((YES)); then
		say "$question yes (--yes)"
		return 0
	fi
	if [[ $default == y ]]; then hint="[Y/n]"; else hint="[y/N]"; fi
	if ((!HAVE_TTY)); then
		say "$question $hint (no keyboard to ask; answering no)"
		return 1
	fi
	while true; do
		printf '%s %s ' "$question" "$hint" >/dev/tty
		answer=""
		IFS= read -r answer </dev/tty || true
		printf '%s %s %s\n' "$question" "$hint" "${answer:-<Enter>}" >>"$LOG_FILE"
		case $(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]') in
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

parse_args() {
	while (($#)); do
		case $1 in
		--purge) PURGE=1 ;;
		--purge-local) PURGE_LOCAL=1 ;;
		--yes | -y) YES=1 ;;
		--from-screen)
			FROM_SCREEN=1
			YES=1
			;;
		--dry-run) DRY_RUN=1 ;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			usage >&2
			die "I don't know the option \"$1\"."
			;;
		esac
		shift
	done
}

setup() {
	if [[ $(id -u) -eq 0 ]]; then
		die "Please run this as your normal user, without sudo; it asks for sudo by itself when it needs to." \
			"For example:  bash ~/.local/share/sunroom-kiosk/uninstall.sh"
	fi
	if ((!FROM_SCREEN)) && { : </dev/tty; } 2>/dev/null; then
		HAVE_TTY=1
	fi
	mkdir -p "$STATE_DIR"
	printf '\n----- %s  uninstall.sh  purge=%s purge-local=%s yes=%s from-screen=%s\n' \
		"$(date '+%Y-%m-%d %H:%M:%S')" "$PURGE" "$PURGE_LOCAL" "$YES" "$FROM_SCREEN" >>"$LOG_FILE"
	exec > >(tee -a "$LOG_FILE") 2>&1
	TMP_DIR=$(mktemp -d)
	trap 'rm -rf "$TMP_DIR"' EXIT
}

need_sudo() {
	if ((SUDO_READY)); then
		return 0
	fi
	if ! sudo -n true 2>/dev/null; then
		note "This step needs administrator rights, so sudo may ask for your password."
		sudo -v || die "sudo didn't accept the password, so the rest was left in place." \
			"Run this again when sudo works for your account."
	fi
	SUDO_READY=1
}

user_systemctl() {
	XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" systemctl --user "$@"
}

load_state() {
	if [[ -r $STATE_FILE ]]; then
		# shellcheck source=/dev/null
		. "$STATE_FILE"
	fi
	STATE_LABWC_AUTOSTART_CREATED=${STATE_LABWC_AUTOSTART_CREATED:-0}
	STATE_TIME_WAIT_SYNC_BY_US=${STATE_TIME_WAIT_SYNC_BY_US:-0}
	STATE_NM_DROPIN=${STATE_NM_DROPIN:-}
	STATE_CMDLINE_FILE=${STATE_CMDLINE_FILE:-}
	STATE_CMDLINE_BACKUP=${STATE_CMDLINE_BACKUP:-}
	STATE_CMDLINE_KEYS=${STATE_CMDLINE_KEYS:-}
	STATE_BACKLIGHT_RULE=${STATE_BACKLIGHT_RULE:-}
	STATE_I2C_MODULES=${STATE_I2C_MODULES:-}
}

remove_units() {
	local unit removed=0
	user_systemctl disable --now sunroom-kiosk-restart.timer >/dev/null 2>&1 || true
	# Sunroom Screen (or, before 0.13.0, the screen helper) switches the screen back on, at full
	# brightness, as it stops.
	user_systemctl stop sunroom-screen.service sunroom-kiosk.service >/dev/null 2>&1 || true
	for unit in "${UNITS[@]}"; do
		if [[ -e $UNIT_DIR/$unit ]]; then
			rm -f "$UNIT_DIR/$unit"
			removed=1
		fi
	done
	rm -f "$UNIT_DIR/timers.target.wants/sunroom-kiosk-restart.timer"
	user_systemctl daemon-reload >/dev/null 2>&1 || true
	user_systemctl reset-failed "${UNITS[@]}" >/dev/null 2>&1 || true
	if ((removed)); then
		note "Stopped Sunroom Screen and removed its services and nightly restart."
	fi
	remove_agent
	if [[ -e $BIN_DIR/sunroom-screen ]]; then
		rm -f "$BIN_DIR/sunroom-screen"
		note "Removed the screen helper ($(tidy "$BIN_DIR/sunroom-screen")); the screen stays on."
	fi
}

find_uv() {
	if command -v uv >/dev/null 2>&1; then
		command -v uv
	elif [[ -x $BIN_DIR/uv ]]; then
		printf '%s' "$BIN_DIR/uv"
	else
		return 1
	fi
}

# A Mac: stop Sunroom Screen and take its LaunchAgent out first (it switches nothing off there).
remove_launch_agent() {
	[[ $(uname -s) == Darwin ]] || return 0
	launchctl bootout "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1 || true
	if [[ -e $LAUNCH_AGENT ]]; then
		rm -f "$LAUNCH_AGENT"
		note "Stopped Sunroom Screen and removed $(tidy "$LAUNCH_AGENT")."
	fi
}

# Sunroom Screen is a uv tool (before 0.13.0, a bash launcher at the same path). On a Mac it set
# the browser's preferences itself, so it takes them out before it goes.
remove_agent() {
	local uv
	if [[ $(uname -s) == Darwin && -x $BIN_DIR/sunroom-kiosk ]]; then
		"$BIN_DIR/sunroom-kiosk" policy --remove >/dev/null 2>&1 || true
		note "Took Sunroom Screen's settings out of the browser's preferences."
	fi
	if uv=$(find_uv) && "$uv" tool list 2>/dev/null | grep -q '^sunroom-kiosk '; then
		"$uv" tool uninstall sunroom-kiosk >/dev/null 2>&1 || warn "uv couldn't uninstall Sunroom Screen; see: uv tool list"
		note "Uninstalled Sunroom Screen."
	fi
	if [[ -e $BIN_DIR/sunroom-kiosk || -L $BIN_DIR/sunroom-kiosk ]]; then
		rm -f "$BIN_DIR/sunroom-kiosk"
		note "Removed $(tidy "$BIN_DIR/sunroom-kiosk")."
	fi
}

# On a Pi, Sunroom Screen's root helper and the sudoers rule that allows it; anywhere, the
# browser's policy files.
remove_root_files() {
	local file
	for file in "$SUDOERS_FILE" "$ROOT_HELPER" "${POLICY_FILES[@]}"; do
		if [[ -e $file ]]; then
			need_sudo
			sudo rm -f "$file"
			note "Removed $file."
		fi
	done
}

# From the screen there's nobody to type sudo's password: the root helper, which sudoers allows
# without one, takes off the files root owns (the browser's policy, the Wi-Fi drop-in, the
# backlight rule, the i2c-dev file), then its sudoers rule and itself. A helper from before 0.17.0
# has no such command: it empties the browser's policy instead, and the rest stays. A computer
# that had no sudo at install has no root files.
remove_root_files_from_screen() {
	local file
	if [[ ! -e $ROOT_HELPER ]]; then
		note "No root helper here, so there are no system files to take off."
		return 0
	fi
	if sudo -n "$ROOT_HELPER" remove-root-files; then
		note "Removed Sunroom Screen's system files and its root helper."
		return 0
	fi
	for file in "${POLICY_FILES[@]}"; do
		if [[ -e $file ]]; then
			printf '{}\n' | sudo -n "$ROOT_HELPER" write-policy "$file" >/dev/null 2>&1 || true
		fi
	done
	warn "the root helper couldn't take its files off, so it emptied the browser's policy." \
		"The rest goes with:  curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash -s -- --uninstall"
}

# The screen helper's system files: the udev rule that lets the video group switch the
# backlight off, and the file that loads i2c-dev (for DDC/CI brightness) at every start.
remove_screen_files() {
	local rule=${STATE_BACKLIGHT_RULE:-$BACKLIGHT_RULE} modules=${STATE_I2C_MODULES:-$I2C_MODULES_FILE}
	if [[ -e $rule ]]; then
		need_sudo
		sudo rm -f "$rule"
		sudo udevadm control --reload >/dev/null 2>&1 || true
		note "Removed the screen helper's backlight rule ($rule)."
	fi
	if [[ -e $modules ]]; then
		need_sudo
		sudo rm -f "$modules"
		note "Removed $modules; the i2c-dev module no longer loads at startup for the screen helper."
	fi
}

strip_block() {
	awk -v begin="$BLOCK_BEGIN" -v end="$BLOCK_END" '
		index($0, begin) == 1 && !inblock { inblock = 1; held = $0; next }
		inblock { held = held "\n" $0; if ($0 == end) { inblock = 0; held = "" } next }
		{ print }
		END { if (inblock) print held }
	' "$1"
}

remove_autostart() {
	local file="$LABWC_DIR/autostart"
	if [[ -f $file ]] && grep -q "^$BLOCK_BEGIN" "$file"; then
		strip_block "$file" | awk '{ line[NR] = $0 } END { n = NR; while (n > 0 && line[n] ~ /^[ \t]*$/) n--; for (i = 1; i <= n; i++) print line[i] }' >"$TMP_DIR/autostart"
		if [[ ! -s $TMP_DIR/autostart && $STATE_LABWC_AUTOSTART_CREATED == 1 ]]; then
			rm -f "$file"
			note "Removed $(tidy "$file") (the installer had created it)."
		else
			cat "$TMP_DIR/autostart" >"$file"
			note "Took Sunroom Screen out of $(tidy "$file")."
		fi
	fi
	if [[ -e $XDG_AUTOSTART_FILE ]]; then
		rm -f "$XDG_AUTOSTART_FILE"
		note "Removed $(tidy "$XDG_AUTOSTART_FILE")."
	fi
}

find_labwc_rule() {
	local dir candidate
	if [[ -n $SCRIPT_PATH && -f $SCRIPT_PATH ]]; then
		dir=$(cd "$(dirname "$SCRIPT_PATH")" && pwd)
		candidate="$dir/labwc-rule.py"
		if [[ -f $candidate ]]; then
			printf '%s' "$candidate"
			return 0
		fi
	fi
	if [[ -f $SHARE_DIR/labwc-rule.py ]]; then
		printf '%s' "$SHARE_DIR/labwc-rule.py"
		return 0
	fi
	return 1
}

remove_labwc_settings() {
	local rule status=0
	if [[ ! -f $LABWC_STATE ]] && ! grep -qs 'sunroom-kiosk' "$LABWC_DIR/rc.xml"; then
		return 0
	fi
	if ! rule=$(find_labwc_rule) || ! command -v python3 >/dev/null 2>&1; then
		warn "couldn't find labwc-rule.py, so $(tidy "$LABWC_DIR/rc.xml") still has the screen's" \
			"pointer and touch settings (marked sunroom-kiosk). Your copy from before is $(tidy "$LABWC_DIR/rc.xml.sunroom-backup")."
		return 0
	fi
	python3 "$rule" --remove 2>&1 | sed 's/^/    /' || status=$?
	if ((status != 0)); then
		warn "couldn't fully take the screen's settings out of $(tidy "$LABWC_DIR/rc.xml")."
	fi
	pkill -HUP -u "$(id -u)" -x labwc 2>/dev/null || true
}

remove_wifi_dropin() {
	local file=${STATE_NM_DROPIN:-$NM_DROPIN}
	if [[ -e $file ]]; then
		need_sudo
		sudo rm -f "$file"
		note "Wi-Fi power saving is back to the Pi's default (after a restart)."
		NEEDS_RESTART=1
	fi
}

undo_time_wait_sync() {
	if [[ $STATE_TIME_WAIT_SYNC_BY_US == 1 ]]; then
		need_sudo
		sudo systemctl disable systemd-time-wait-sync.service >/dev/null 2>&1 || true
		note "Turned off systemd-time-wait-sync again (the installer had turned it on)."
	fi
}

# Put back the kernel command line options the installer replaced or added, one option
# (key) at a time, from the copy it kept before its first change.
restore_cmdline() {
	local file=$STATE_CMDLINE_FILE backup=$STATE_CMDLINE_BACKUP line original="" token key keep new_line
	local -a keys tokens original_tokens new_tokens=()
	[[ -n $file && -n $STATE_CMDLINE_KEYS ]] || return 0
	need_sudo
	if ! sudo test -f "$file"; then
		warn "couldn't find $file to take out the screen options; nothing changed there."
		return 0
	fi
	line=$(sudo cat "$file")
	if [[ -z $line || $line == *$'\n'* ]]; then
		warn "$file isn't a single line any more, so it was left alone." \
			"Remove these options from it by hand if they are still there: $STATE_CMDLINE_KEYS"
		return 0
	fi
	if [[ -n $backup ]] && sudo test -f "$backup"; then
		original=$(sudo cat "$backup")
	fi
	read -ra keys <<<"$STATE_CMDLINE_KEYS"
	read -ra tokens <<<"$line"
	read -ra original_tokens <<<"$original"
	for token in "${tokens[@]}"; do
		keep=1
		for key in "${keys[@]}"; do
			if [[ $token == "$key"* ]]; then
				keep=0
			fi
		done
		if ((keep)); then
			new_tokens+=("$token")
		fi
	done
	for key in "${keys[@]}"; do
		for token in "${original_tokens[@]}"; do
			if [[ $token == "$key"* ]]; then
				new_tokens+=("$token")
			fi
		done
	done
	new_line="${new_tokens[*]}"
	if [[ $new_line != "$line" ]]; then
		printf '%s\n' "$new_line" >"$TMP_DIR/cmdline.txt"
		sudo cp "$TMP_DIR/cmdline.txt" "$file"
		sync
		note "Took the screen options back out of $file."
		NEEDS_RESTART=1
	fi
	if [[ -n $backup ]]; then
		sudo rm -f "$backup"
	fi
}

remove_config() {
	if [[ -d $CONFIG_DIR/profile ]]; then
		say ""
		say "The screen's browser data holds its pairing with Sunroom."
		if ask_yes_no "Delete it too? The screen would need to be paired again." n; then
			rm -rf "$CONFIG_DIR"
			note "Deleted the screen's browser data and settings."
			return 0
		fi
		note "Kept the browser data (and the pairing) in $(tidy "$CONFIG_DIR/profile")."
	fi
	if [[ -e $CONFIG_DIR/config ]]; then
		rm -f "$CONFIG_DIR/config"
		note "Removed the screen's settings."
	fi
	rmdir "$CONFIG_DIR" 2>/dev/null || true
}

purge_server() {
	say ""
	if [[ ! -d $SERVER_DIR ]]; then
		note "Sunroom's server isn't installed in $SERVER_DIR on this Pi; nothing more to delete."
		return 0
	fi
	if ! ask_yes_no "Delete Sunroom and ALL its data (calendars, lists, photos) from this Pi? This can't be undone." n; then
		note "Kept Sunroom and its data."
		PURGE=0
		return 0
	fi
	need_sudo
	if command -v docker >/dev/null 2>&1; then
		if [[ -f $SERVER_DIR/docker-compose.yml ]]; then
			sudo docker compose --project-directory "$SERVER_DIR" -f "$SERVER_DIR/docker-compose.yml" down -v ||
				warn "docker compose down didn't finish; removing the container and data directly."
		fi
		sudo docker rm -f sunroom >/dev/null 2>&1 || true
		sudo docker volume rm sunroom_data >/dev/null 2>&1 || true
	fi
	sudo rm -rf "$SERVER_DIR"
	sudo rm -f "$AVAHI_SERVICE"
	note "Deleted Sunroom, its data and $SERVER_DIR. Docker itself is still installed."
}

# Sunroom run on this computer as a program: here while its service or Sunroom Screen's note is.
local_sunroom_here() {
	[[ -e $LOCAL_UNIT || -e $LOCAL_LAUNCH_AGENT || -e $LOCAL_STATE ]]
}

purge_local_sunroom() {
	local uv
	local_sunroom_here || return 0
	say ""
	if ! ask_yes_no "Delete Sunroom, which runs on this computer, and ALL its data (calendars, lists, photos)? This can't be undone." n; then
		note "Kept Sunroom and its data."
		PURGE=0
		return 0
	fi
	if [[ -e $LOCAL_UNIT ]]; then
		user_systemctl disable --now sunroom.service >/dev/null 2>&1 || true
		rm -f "$LOCAL_UNIT"
		user_systemctl daemon-reload >/dev/null 2>&1 || true
	fi
	if [[ -e $LOCAL_LAUNCH_AGENT ]]; then
		launchctl bootout "gui/$(id -u)/$LOCAL_LAUNCH_AGENT_LABEL" >/dev/null 2>&1 || true
		rm -f "$LOCAL_LAUNCH_AGENT"
	fi
	if uv=$(find_uv) && "$uv" tool list 2>/dev/null | grep -q '^sunroom '; then
		"$uv" tool uninstall sunroom >/dev/null 2>&1 || warn "uv couldn't uninstall Sunroom; see: uv tool list"
	fi
	rm -rf "$LOCAL_DATA"
	rm -f "$LOCAL_STATE"
	note "Deleted Sunroom, which ran on this computer, and its data ($(tidy "$LOCAL_DATA"))."
}

finish() {
	local keep_uninstaller=0
	rm -f "$STATE_FILE" "$LABWC_STATE" "$STATE_DIR/update.json"
	# While Sunroom stays (the Pi's server, or the program run here), keep this script so --purge
	# still works later.
	if ((!PURGE)) && { [[ -d $SERVER_DIR ]] || local_sunroom_here; } && [[ -f $SHARE_DIR/uninstall.sh ]]; then
		keep_uninstaller=1
		find "$SHARE_DIR" -mindepth 1 ! -name uninstall.sh -exec rm -rf {} + 2>/dev/null || true
	else
		rm -rf "$SHARE_DIR"
	fi
	say ""
	say "The Sunroom screen setup is removed."
	if command -v raspi-config >/dev/null 2>&1; then
		say "Left as they are: uv, Docker, the desktop logging in by itself and screen blanking being off"
		say "(change those in Raspberry Pi Configuration if you like)."
	else
		say "Left as it is: uv, which installed Sunroom Screen."
	fi
	if ((!PURGE)) && { [[ -d $SERVER_DIR ]] || local_sunroom_here; }; then
		if [[ -d $SERVER_DIR ]]; then
			say "Sunroom itself still runs on this Pi, with your family's data. To delete it as well:"
		else
			say "Sunroom itself still runs on this computer, with your family's data ($(tidy "$LOCAL_DATA"))."
			say "To delete it as well:"
		fi
		if ((keep_uninstaller)); then
			say "  bash ~/.local/share/sunroom-kiosk/uninstall.sh --purge"
		else
			say "  bash kiosk/install.sh --uninstall --purge"
		fi
	fi
	if ((NEEDS_RESTART)); then
		say "Restart the Pi to finish (sudo reboot)."
	fi
	say "Log: $(tidy "$LOG_FILE")"
}

# --dry-run: what a real run would take off here, from what's here; nothing changes.
plan() {
	local file root_files=0
	say "Sunroom uninstaller: a dry run. Nothing on this computer changes."
	say ""
	say "A real run would:"
	if [[ -e $BIN_DIR/sunroom-kiosk || -e $LAUNCH_AGENT || -e $UNIT_DIR/sunroom-kiosk.service ]]; then
		say "  - stop Sunroom Screen and uninstall it, with its service and start-up entries"
	fi
	for file in "$SUDOERS_FILE" "$ROOT_HELPER" "${POLICY_FILES[@]}" "$NM_DROPIN" "$BACKLIGHT_RULE" "$I2C_MODULES_FILE"; do
		[[ -e $file ]] && root_files=1
	done
	if ((FROM_SCREEN)) && [[ -e $ROOT_HELPER ]]; then
		say "  - take the system files off through Sunroom Screen's root helper, without a password"
	elif ((FROM_SCREEN)); then
		say "  - find no root helper, so no system files to take off"
	elif ((root_files)); then
		say "  - remove the system files it put in, with sudo (the browser's policy, the root helper)"
	fi
	if [[ -d $CONFIG_DIR/profile ]] && ((YES)); then
		say "  - delete the screen's browser data (its pairing) and settings"
	elif [[ -d $CONFIG_DIR/profile ]]; then
		say "  - ask before deleting the screen's browser data, which holds its pairing"
	elif [[ -e $CONFIG_DIR/config ]]; then
		say "  - remove the screen's settings"
	fi
	if ((PURGE || PURGE_LOCAL)) && local_sunroom_here; then
		say "  - stop Sunroom, which runs on this computer, and delete it and ALL its data ($(tidy "$LOCAL_DATA"))"
	elif local_sunroom_here; then
		say "  - leave Sunroom, which runs on this computer, and its data as they are"
	fi
	if ((PURGE)) && [[ -d $SERVER_DIR ]]; then
		say "  - delete Sunroom's Docker setup in $SERVER_DIR and ALL its data"
	elif [[ -d $SERVER_DIR ]]; then
		say "  - leave Sunroom's Docker setup in $SERVER_DIR and its data as they are"
	fi
	say "uv, Docker and the computer's own settings stay as they are."
}

main() {
	parse_args "$@"
	if ((DRY_RUN)); then
		plan
		return 0
	fi
	setup
	load_state
	say "Removing the Sunroom screen setup..."
	remove_launch_agent
	remove_units
	if ((FROM_SCREEN)); then
		remove_root_files_from_screen
	else
		remove_root_files
	fi
	remove_autostart
	remove_labwc_settings
	if ((FROM_SCREEN)); then
		if [[ -n $STATE_CMDLINE_KEYS || $STATE_TIME_WAIT_SYNC_BY_US == 1 ]]; then
			note "The Pi's start-up settings stay; the installer's --uninstall in a terminal takes them out."
		fi
	else
		remove_wifi_dropin
		remove_screen_files
		undo_time_wait_sync
		restore_cmdline
	fi
	remove_config
	if ((PURGE)); then
		purge_server
		purge_local_sunroom
	elif ((PURGE_LOCAL)); then
		purge_local_sunroom
	fi
	finish
}

main "$@"
