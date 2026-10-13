"""Write the API description (OpenAPI) to build/openapi.json, for generating frontend types.

    .venv/bin/python scripts/export_openapi.py && (cd frontend && npm run api)

No database is needed: the description comes from the code.
"""

import json
from pathlib import Path

from ziira.kernel.app import create_app

OUT = Path(__file__).resolve().parent.parent / "build" / "openapi.json"

if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(create_app().openapi(), indent=1))
    print(f"Wrote {OUT}")
