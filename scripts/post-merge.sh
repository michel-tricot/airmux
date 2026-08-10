#!/bin/bash
set -e
bun install --frozen-lockfile

# Task merges keep stripping the [[ports]] block from .replit, which lets the
# dev preview route to the backend instead of the console. Restore the pin
# (console Vite 20383 -> external 80) whenever it goes missing.
if ! grep -q '^\[\[ports\]\]' .replit; then
  cat >> .replit <<'PORTS'

[[ports]]
localPort = 20383
externalPort = 80
PORTS
  echo "post-merge: restored [[ports]] preview pin in .replit"
fi
