#!/usr/bin/env bash
# One command to run the RolledCo servicing demo.
#   ./run.sh                  -> http://localhost:8000
#   PORT=8080 ./run.sh        -> different port
#   DEMO_TODAY=2027-01-15     -> the frozen clock (default shown)
#   ANTHROPIC_API_KEY=...     -> enables "Re-run Extraction" (live call)
#   ANTHROPIC_MODEL=...       -> model for the live call (default claude-opus-5-5)
cd "$(dirname "$0")"
exec python3 app/server.py
