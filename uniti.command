#!/bin/sh

case "$0" in
    /*) launcher_path=$0 ;;
    *) launcher_path=$PWD/$0 ;;
esac

launcher_dir=$(CDPATH= cd -- "${launcher_path%/*}" && pwd -P) || exit 1
bootstrap=$launcher_dir/scripts/bootstrap.py

if [ -n "${UNITI_PYTHON:-}" ]; then
    exec "$UNITI_PYTHON" "$bootstrap" "$@"
fi

for candidate in python3 python3.15 python3.14 python3.13 python3.12 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" "$bootstrap" "$@"
    fi
done

printf '%s\n' 'UNITI requires an installed Python 3.12 or newer.' >&2
exit 10
