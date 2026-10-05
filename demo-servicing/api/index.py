"""Vercel entry point. Serves the same FastAPI app as app/server.py."""
import os
import sys
from pathlib import Path

os.environ.setdefault("STATE_DIR", "/tmp/rolledco")
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.server import app  # noqa: E402,F401
