#!/bin/bash
# Commits and pushes any pending changes so the repo is never more than 2 weeks stale.
set -e
cd "/Users/maxalderman/AI Agents - Max"

git add -A

if git diff --cached --quiet; then
  echo "$(date): no changes to back up."
  exit 0
fi

git commit -m "Automated backup $(date +%Y-%m-%d)"
git push origin main
echo "$(date): backup pushed."
