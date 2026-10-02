import argparse
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(
    description="Create a new environment file without printing secrets or replacing existing configuration."
)
parser.add_argument("--production", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; preserve and edit the existing configuration")
template = root / (".env.production.example" if args.production else ".env.example")
values = template.read_text()
for key in ("POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "POSTGRES_APP_PASSWORD"):
    values = values.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(60)}\n")
with target.open("x", encoding="utf-8", newline="\n") as output:
    output.write(values)
target.chmod(0o600)
print("Created .env with independent generated secrets; review deployment settings before starting")
