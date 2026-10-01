# gevent must patch sockets/threads before anything else imports them.
from gevent import monkey

monkey.patch_all()

from psycogreen.gevent import patch_psycopg  # noqa: E402

patch_psycopg()  # make psycopg2 cooperative so a slow query never blocks other greenlets

from app import create_app  # noqa: E402

app = create_app()
