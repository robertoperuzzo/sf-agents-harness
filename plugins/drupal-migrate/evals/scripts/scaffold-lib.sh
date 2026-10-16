#!/bin/sh
# scaffold-lib.sh: shared workspace preparation for drupal-migrate eval cases.
#
# A case's scaffold.sh sources this file and calls `dm_scaffold <fixture> [phase1]`.
# The runner executes scaffold.sh in the fresh run workspace (cwd) with a minimal
# environment and a time limit, so everything here is resolved from the case
# directory, never from PATH or the caller's environment.
#
#   dm_scaffold drupal10          # config + entity context under .agents/references/migrate/
#   dm_scaffold drupal10 phase1   # same, plus an empty doc/ for as-is output
#
# Exit 1 with a `fixture up <name>` hint when the fixture container is not
# running, or a `fixture serve` hint when the host executor is not alive, so the
# run scores 0 instead of grading an agent that never had a database.
#
# The agent's shell is sandboxed: no network, no Docker, no read access to the
# plugin checkout. So the workspace gets the file-queue client as
# .agents/bin/fixture and the workspace path is registered for `fixture serve`,
# which executes the queued statements on the host (design D4).

dm_scaffold() {
  dm_fixture=$1
  dm_phase=${2:-}
  dm_case_dir=$(cd "$(dirname "$0")" && pwd)
  dm_evals_dir=$dm_case_dir
  # walk up to the eval dir, the one that holds fixtures/bin/fixture
  while [ ! -x "$dm_evals_dir/fixtures/bin/fixture" ]; do
    dm_parent=$(dirname "$dm_evals_dir")
    if [ "$dm_parent" = "$dm_evals_dir" ]; then
      echo "scaffold: cannot find fixtures/bin/fixture above $dm_case_dir" >&2
      return 1
    fi
    dm_evals_dir=$dm_parent
  done
  dm_plugin_dir=$(dirname "$dm_evals_dir")
  dm_fixture_bin="$dm_evals_dir/fixtures/bin/fixture"
  dm_fixture_dir="$dm_evals_dir/fixtures/$dm_fixture"
  dm_docker=$(command -v docker 2>/dev/null || true)
  for dm_candidate in /usr/local/bin/docker /opt/homebrew/bin/docker /usr/bin/docker; do
    [ -n "$dm_docker" ] && break
    [ -x "$dm_candidate" ] && dm_docker=$dm_candidate
  done
  if [ -z "$dm_docker" ]; then
    echo "scaffold: docker not found; the $dm_fixture fixture cannot be running. Install Docker and run: fixture up $dm_fixture" >&2
    return 1
  fi
  if [ "$("$dm_docker" inspect -f '{{.State.Running}}' "dm-fixture-$dm_fixture" 2>/dev/null)" != "true" ]; then
    echo "scaffold: fixture container dm-fixture-$dm_fixture is not running. Start it first: $dm_fixture_bin up $dm_fixture" >&2
    return 1
  fi
  # HOME is a temporary directory here; the registry lives in the real home.
  dm_state=${DM_FIXTURE_STATE_DIR:-$(eval "printf '%s' ~$(id -un)")/.cache/dm-fixture}
  dm_serve_pid=$(cat "$dm_state/serve.pid" 2>/dev/null || true)
  if [ -z "$dm_serve_pid" ] || ! kill -0 "$dm_serve_pid" 2>/dev/null; then
    echo "scaffold: the host executor is not running (no live pid in $dm_state/serve.pid). Start it first, in another terminal: $dm_fixture_bin serve" >&2
    return 1
  fi
  if [ ! -f "$dm_fixture_dir/project-config.md" ]; then
    echo "scaffold: $dm_fixture_dir/project-config.md missing" >&2
    return 1
  fi
  mkdir -p .agents/references/migrate .agents/bin .agents/queue
  cp "$dm_plugin_dir/references/entity-type-context.md" .agents/references/migrate/entity-type-context.md
  # File-queue client in place of the Docker-backed script; the installed config
  # names the relative path instead of the bare `fixture` command.
  cp "$dm_evals_dir/fixtures/bin/fixture-client" .agents/bin/fixture
  chmod +x .agents/bin/fixture
  mkdir -p "$dm_state/workspaces"
  dm_ws=$(pwd)
  printf '%s\n' "$dm_ws" >"$dm_state/workspaces/$(printf '%s' "$dm_ws" | cksum | cut -d' ' -f1)"
  # shellcheck disable=SC2016 # literal backticks are Markdown, not command substitution
  sed -E -e 's#`fixture (query|up|down|status) #`.agents/bin/fixture \1 #g' \
      -e 's#^fixture (query|up|down|status) #.agents/bin/fixture \1 #' \
      "$dm_fixture_dir/project-config.md" > .agents/references/migrate/project-config.md
  if [ "$dm_phase" = "phase1" ]; then
    mkdir -p doc
  fi
  echo "scaffold: workspace ready for fixture $dm_fixture (queue client at .agents/bin/fixture, registered for fixture serve pid $dm_serve_pid)"
  return 0
}
