import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

host = urlsplit(os.environ.get("DJANGO_PUBLIC_BASE_URL", "http://127.0.0.1:8000")).netloc
request = Request("http://127.0.0.1:8000/healthz/", headers={"Host": host})
with urlopen(request, timeout=5) as response:
    if response.status != 200:
        raise SystemExit(1)
