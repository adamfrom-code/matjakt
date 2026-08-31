"""Static file server for frontend/ during pure UI development.

Honours the PORT environment variable (falling back to 5500) so the dev
harness can assign a free port instead of colliding with whatever already
holds 5500. `python -m http.server 5500` could not do this - the port is a
positional argument there, so it was hardcoded in the npm script.

NOTE: this serves static files ONLY. It cannot answer /api, so the app's
same-origin API calls will 404 against it. For anything involving prices,
recipes or accounts, run the backend instead (`npm run backend`) - it serves
the app at http://127.0.0.1:8000/app/ AND the API at /api, same-origin.
Cross-origin use of this server would also need its port listed in
MATJAKT_FRONTEND_ORIGIN, which defaults to http://localhost:5500.
"""

import functools
import http.server
import os
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1] / "frontend"

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 5500)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DIRECTORY))
    print(f"Serving {DIRECTORY} at http://127.0.0.1:{port}/ (app at /app/)")
    http.server.test(HandlerClass=handler, port=port, bind="127.0.0.1")
