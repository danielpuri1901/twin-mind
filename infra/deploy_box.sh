#!/bin/sh
# Deploys one commit to the box. The ship gate runs on a separate copy first,
# so a red gate never reaches the live folder. After the checkout it installs the
# copies that live outside the folder, then proves that the box matches the repo.
# Usage from the laptop: ssh twin-mind 'sh ~/super-project/infra/deploy_box.sh [commit]'
set -eu
main() {
  LIVE="$HOME/super-project"
  git -C "$LIVE" fetch --quiet origin main
  WANT=$(git -C "$LIVE" rev-parse --verify "${1:-origin/main}^{commit}")
  COPY=$(mktemp -d)
  trap 'git -C "$LIVE" worktree remove --force "$COPY"; rm -rf "$COPY"' EXIT
  git -C "$LIVE" worktree add --quiet --detach --force "$COPY" "$WANT"
  sh "$COPY/evals/eval.sh"
  git -C "$LIVE" checkout --quiet --detach "$WANT"
  sh "$LIVE/infra/install_box.sh"
  sh "$LIVE/infra/check_box.sh"
}
# The checkout replaces this file while it runs, so the shell must read all of it before it starts.
main "$@"
