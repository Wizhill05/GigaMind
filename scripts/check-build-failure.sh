#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
cat > "$tmp/npm" <<'MOCK'
#!/bin/sh
case "$1" in
  ci) exit "$TASK_INSTALL_EXIT";;
  run) exit "$TASK_BUILD_EXIT";;
  *) exit 99;;
esac
MOCK
cat > "$tmp/python" <<'MOCK'
#!/bin/sh
touch "$TASK_MARKER"
exit "$TASK_PYTHON_EXIT"
MOCK
chmod +x "$tmp/npm" "$tmp/python"
check() {
    install_exit=$1 build_exit=$2 python_exit=$3 expected=$4 python_expected=$5
    marker="$tmp/python-$install_exit-$build_exit-$python_exit"
    status=0
    TASK_MARKER="$marker" TASK_INSTALL_EXIT="$install_exit" \
      TASK_BUILD_EXIT="$build_exit" TASK_PYTHON_EXIT="$python_exit" \
      PATH="$tmp:$PATH" "$root/scripts/build.sh" || status=$?
    if [ "$status" -ne "$expected" ]; then
        printf 'Expected exit %s, received %s\n' "$expected" "$status" >&2
        exit 1
    fi
    if [ "$python_expected" = yes ]; then
        [ -f "$marker" ] || { printf '%s\n' 'Python install was not reached' >&2; exit 1; }
    elif [ -e "$marker" ]; then
        printf '%s\n' 'Python install ran after frontend failure' >&2
        exit 1
    fi
}
check 46 0 0 46 no
check 0 47 0 47 no
check 0 0 48 48 yes
check 0 0 0 0 yes
printf '%s\n' 'Install and build failures propagate; successful builds reach Python.'
