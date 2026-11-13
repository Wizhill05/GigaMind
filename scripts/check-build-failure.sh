#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
cat > "$tmp/npm" <<'MOCK'
#!/bin/sh
case "$1" in ci) exit 0;; run) exit 47;; *) exit 99;; esac
MOCK
cat > "$tmp/python" <<'MOCK'
#!/bin/sh
touch "$TASK_MARKER"
MOCK
chmod +x "$tmp/npm" "$tmp/python"
status=0
TASK_MARKER="$tmp/python-ran" PATH="$tmp:$PATH" "$root/scripts/build.sh" || status=$?
[ "$status" -eq 47 ] && [ ! -e "$tmp/python-ran" ]
printf '%s\n' 'Frontend failure propagated; Python install was not invoked.'
