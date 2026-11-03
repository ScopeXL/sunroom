#!/usr/bin/env bash
# Sunroom updater for a Raspberry Pi that runs Sunroom itself (the "all on the Pi" and
# --server-only installs). kiosk/install.sh copies it to /opt/sunroom/update.sh.
#
#   sudo /opt/sunroom/update.sh           update to the newest version
#   sudo /opt/sunroom/update.sh 0.6.0     switch to exactly that version (also how to go back)
#
# It pins the version in /opt/sunroom/docker-compose.yml (no version means "latest"),
# downloads it, restarts the container, waits for /api/health and prints the version
# Sunroom reports, or Sunroom's last 40 log lines if it does not come back. The family's
# data lives in the sunroom_data volume and is kept; Sunroom copies its database before
# any upgrade that changes it. See docs/PLAN.md §13.2 and §13.6.

set -euo pipefail

SUNROOM_DIR="/opt/sunroom"
SUNROOM_IMAGE="scopexl/sunroom"
COMPOSE_FILE="$SUNROOM_DIR/docker-compose.yml"
HEALTH_TIMEOUT=300

say() {
	printf '%s\n' "$*"
}

die() {
	printf '\n' >&2
	printf '%s\n' "$@" >&2
	exit 1
}

usage() {
	cat <<'EOF'
Update Sunroom on this Raspberry Pi.

  sudo /opt/sunroom/update.sh           update to the newest version
  sudo /opt/sunroom/update.sh 0.6.0     switch to exactly that version (also how to go back)

Your calendars, lists and photos are kept.
EOF
}

compose() {
	docker compose --project-directory "$SUNROOM_DIR" -f "$COMPOSE_FILE" "$@"
}

# The tag in "image: scopexl/sunroom:<tag>"; empty when there is none.
current_tag() {
	awk -v image="$SUNROOM_IMAGE" '
		$1 == "image:" {
			value = $2
			gsub(/["\047]/, "", value)
			if (index(value, image ":") == 1) { print substr(value, length(image) + 2); exit }
		}' "$COMPOSE_FILE"
}

set_tag() {
	local tag=$1 tmp
	tmp=$(mktemp)
	sed -E "s#^([[:space:]]*image:[[:space:]]*[\"']?)${SUNROOM_IMAGE}(:[^[:space:]\"']*)?#\\1${SUNROOM_IMAGE}:${tag}#" "$COMPOSE_FILE" >"$tmp"
	if ! grep -Eq "image:[[:space:]]*[\"']?${SUNROOM_IMAGE}:${tag}([[:space:]\"']|$)" "$tmp"; then
		rm -f "$tmp"
		die "Couldn't find the line \"image: ${SUNROOM_IMAGE}:...\" in $COMPOSE_FILE, so nothing was changed." \
			"Run the installer again to rewrite that file."
	fi
	cat "$tmp" >"$COMPOSE_FILE" # keeps the file's owner and permissions
	rm -f "$tmp"
}

host_port() {
	local line
	line=$(compose port sunroom 7867 2>/dev/null | head -n 1 || true)
	if [[ $line =~ :([0-9]+)$ ]]; then
		printf '%s\n' "${BASH_REMATCH[1]}"
		return
	fi
	line=$(grep -Eo '[0-9]+:7867' "$COMPOSE_FILE" | head -n 1 || true)
	printf '%s\n' "${line%%:*}"
}

json_version() {
	if command -v jq >/dev/null 2>&1; then
		jq -r '.version // empty' 2>/dev/null || true
	elif command -v python3 >/dev/null 2>&1; then
		python3 -c 'import json, sys; print(json.load(sys.stdin).get("version", ""))' 2>/dev/null || true
	else
		sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p'
	fi
}

running_version() {
	local port=$1 body
	body=$(curl -fsS --max-time 5 "http://localhost:$port/api/version" 2>/dev/null) || return 0
	printf '%s' "$body" | json_version
}

wait_healthy() {
	local port=$1 waited=0 code
	while ((waited < HEALTH_TIMEOUT)); do
		code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:$port/api/health" 2>/dev/null || true)
		if [[ $code == 200 ]]; then
			return 0
		fi
		sleep 2
		waited=$((waited + 2))
		if ((waited % 30 == 0)); then
			say "  still starting ($waited seconds)..."
		fi
	done
	return 1
}

show_logs_and_fail() {
	local old_version=$1
	say ""
	say "Sunroom's last 40 log lines:"
	docker logs --tail 40 sunroom 2>&1 || compose logs --tail 40 2>&1 || true
	if [[ $old_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
		die "Sunroom didn't come back after the update. Its last log lines are above." \
			"To go back to the version you had, run:  sudo /opt/sunroom/update.sh $old_version"
	fi
	die "Sunroom didn't come back after the update. Its last log lines are above." \
		"To go back, run  sudo /opt/sunroom/update.sh X.Y.Z  with the version you had before."
}

main() {
	local version="" tag old_tag old_version old_image new_image port new_version

	while (($#)); do
		case $1 in
		-h | --help)
			usage
			exit 0
			;;
		[0-9]*.[0-9]*.[0-9]*)
			[[ $1 =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "\"$1\" isn't a version number like 0.6.0."
			version=$1
			;;
		v[0-9]*)
			die "Leave out the v: for example  sudo /opt/sunroom/update.sh ${1#v}"
			;;
		*)
			usage >&2
			die "I don't understand \"$1\"."
			;;
		esac
		shift
	done

	if [[ $(id -u) -ne 0 ]]; then
		if command -v sudo >/dev/null 2>&1; then
			say "Updating needs administrator rights; asking sudo."
			exec sudo -- bash "$(readlink -f "$0")" ${version:+"$version"}
		fi
		die "Please run:  sudo /opt/sunroom/update.sh"
	fi
	[[ -f $COMPOSE_FILE ]] || die "Sunroom isn't installed in $SUNROOM_DIR on this Pi, so there is nothing to update." \
		"If Sunroom runs on another computer, update it there: docker compose pull && docker compose up -d in its folder."
	command -v docker >/dev/null 2>&1 || die "Docker isn't installed, so Sunroom can't run here. Run the installer again."
	docker compose version >/dev/null 2>&1 || die "Docker's compose tool is missing. Run the installer again; it adds it."

	tag=${version:-latest}
	old_tag=$(current_tag)
	old_tag=${old_tag:-latest}
	port=$(host_port)
	port=${port:-7867}
	old_version=$(running_version "$port")
	old_image=$(docker inspect --format '{{.Image}}' sunroom 2>/dev/null || true)

	say "Sunroom now: ${old_version:-not answering} (image $SUNROOM_IMAGE:$old_tag)."
	say "Getting: $SUNROOM_IMAGE:$tag"
	if [[ $tag != "$old_tag" ]]; then
		set_tag "$tag"
	fi
	if ! compose pull; then
		if [[ $tag != "$old_tag" ]]; then
			set_tag "$old_tag"
		fi
		die "Couldn't download $SUNROOM_IMAGE:$tag, so nothing was changed." \
			"Check the internet connection${version:+ and that version $version exists}, then try again."
	fi

	say "Restarting Sunroom..."
	compose up -d || show_logs_and_fail "$old_version"
	port=$(host_port)
	port=${port:-7867}
	wait_healthy "$port" || show_logs_and_fail "$old_version"

	new_version=$(running_version "$port")
	new_image=$(docker inspect --format '{{.Image}}' sunroom 2>/dev/null || true)
	if [[ -n $old_image && $old_image == "$new_image" ]]; then
		say "Sunroom was already up to date: version ${new_version:-unknown}."
	else
		say "Sunroom is now running version ${new_version:-unknown}."
	fi
}

main "$@"
