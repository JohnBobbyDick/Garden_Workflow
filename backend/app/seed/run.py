"""``python -m app.seed.run`` — seed the built-in template library (idempotent)."""

from app.db import get_db
from app.seed.builtin_templates import seed_builtin_templates

if __name__ == "__main__":
    print(f"built-in templates created: {seed_builtin_templates(get_db())}")
