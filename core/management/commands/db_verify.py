"""Verify database integrity/connectivity after backup or restore."""
import json
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Run a lightweight database integrity/connectivity check.'

    def handle(self, *args, **options):
        db = settings.DATABASES['default']
        engine = db['ENGINE']
        checks = {}
        ok = True
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        checks['connectivity'] = True

        if 'sqlite3' in engine:
            name = str(db.get('NAME') or '')
            if name and name != ':memory:':
                con = sqlite3.connect(name)
                try:
                    row = con.execute('PRAGMA integrity_check').fetchone()
                    checks['integrity_check'] = (row[0] if row else 'unknown')
                    ok = checks['integrity_check'] == 'ok'
                finally:
                    con.close()
            else:
                checks['integrity_check'] = 'skipped_memory_db'
        elif 'postgresql' in engine:
            checks['integrity_check'] = 'requires_pg_dump_restore_test'
        else:
            checks['integrity_check'] = 'unsupported_engine'
            ok = False

        self.stdout.write(json.dumps({'ok': ok, 'engine': engine, 'checks': checks},
                                     ensure_ascii=False))
