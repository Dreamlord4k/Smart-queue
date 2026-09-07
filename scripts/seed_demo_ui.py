from __future__ import annotations

import json

from backend.auth.dependencies import SessionLocal
from backend.demo import reset_demo_ui


def main() -> None:
    with SessionLocal() as db:
        result = reset_demo_ui(db)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
