"""Start (or reuse) a self-contained PostgreSQL from the `pgserver` wheel and print its URI.

No Homebrew, Docker or compiler needed. Data lives in .run/pgdata and the server keeps
running after this script exits.
"""
import sys
from pathlib import Path

import pgserver

data = Path(sys.argv[1] if len(sys.argv) > 1 else ".run/pgdata").resolve()
data.mkdir(parents=True, exist_ok=True)
srv = pgserver.get_server(data, cleanup_mode=None)   # None = leave it running
print(srv.get_uri())
