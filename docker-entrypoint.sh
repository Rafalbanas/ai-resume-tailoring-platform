#!/bin/sh
set -eu

data_path="${DATA_DIR:-/app/data}"
mkdir -p "$data_path/generated" "$data_path/.drafts" "$data_path/profile_photo" "$data_path/reference_cvs"
chown -R appuser:appuser "$data_path"

exec gosu appuser "$@"
