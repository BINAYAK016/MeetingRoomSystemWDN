import argparse
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(
    description="Create a new environment file without printing secrets or replacing existing configuration."
)
parser.add_argument("--production", action="store_true")
parser.add_argument(
    "--http", action="store_true", help="Select the private-network production HTTP template."
)
args = parser.parse_args()
if args.http and not args.production:
    parser.error("--http requires --production")
root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; preserve and edit the existing configuration")
template_name = ".env.example"
if args.production:
    template_name = ".env.production.http.example" if args.http else ".env.production.example"
template = root / template_name
values = template.read_text()
for key in ("POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "POSTGRES_APP_PASSWORD"):
    values = values.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(60)}\n")
with target.open("x", encoding="utf-8", newline="\n") as output:
    output.write(values)
target.chmod(0o600)
print("Created .env with independent generated secrets; review deployment settings before starting")
