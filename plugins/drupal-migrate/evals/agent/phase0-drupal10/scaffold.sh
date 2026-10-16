#!/bin/sh
# Workspace preparation for this case: fixture config + entity context + queue client.
set -eu
# shellcheck disable=SC1091 # the library sits two levels up; resolved at run time
. "$(dirname "$0")/../../scripts/scaffold-lib.sh"
dm_scaffold drupal10
