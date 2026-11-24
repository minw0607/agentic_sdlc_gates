#!/usr/bin/env bash
# Policy comes from the BASE commit of the repo under review, never from the PR, so a PR can't
# relax the rules that judge it. If a file isn't on the base branch yet (first adoption), the
# kit's default is used and a notice says so.
set -euo pipefail
cd "$GITHUB_WORKSPACE"
base="${GATES_BASE_REF:?GATES_BASE_REF is not set}"

# Fail closed: without the base commit there is no trusted policy to read.
git -C target cat-file -e "${base}^{commit}"

mkdir -p policy
from_base() {  # from_base <path in client repo> <destination> <kit default>
  if git -C target cat-file -e "${base}:$1" 2>/dev/null; then
    git -C target show "${base}:$1" > "$2"
  else
    cp "$3" "$2"
    echo "::notice::$1 is not on the base branch; using the kit default"
  fi
}
from_base gates.yaml     policy/gates.yaml    gates-src/defaults/gates.yaml
from_base .gitleaks.toml policy/gitleaks.toml gates-src/defaults/gitleaks.toml

# Tickets as they were before this PR, so a PR can't clean up its own ticket.
# (Sketch: assumes tickets/ at the repo root. With a live Jira connector this goes away.)
mkdir -p policy/tickets
if git -C target cat-file -e "${base}:tickets" 2>/dev/null; then
  git -C target archive "$base" tickets | tar -x -C policy
fi
