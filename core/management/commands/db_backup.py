"""Create a consistent database backup (SQLite file backup or pg_dump)."""
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create a timestamped database backup under backups/.'

    def add_arguments(self, parser):
        parser.add_argument('--out', help='Destination file path (optional)')

    def handle(self, *args, **options):
        db = settings.DATABASES['default']
        engine = db['ENGINE']
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        if options.get('out'):
            dest = Path(options['out'])
        else:
            ext = 'dump' if 'postgresql' in engine else 'sqlite3'
            dest = settings.BASE_DIR / 'backups' / f'db-{stamp}.{ext}'
        dest.parent.mkdir(parents=True, exist_ok=True)

        if 'sqlite3' in engine:
            name = str(db.get('NAME') or '')
            if not name or name == ':memory:':
                raise CommandError('SQLite backup requires a file database, not :memory:')
            src = sqlite3.connect(name)
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        elif 'postgresql' in engine:
            pg_dump = shutil.which('pg_dump')
            if not pg_dump:
                raise CommandError('pg_dump is not installed; install PostgreSQL client tools')
            url = os.environ.get('DATABASE_URL', '').strip()
            if not url:
                raise CommandError('DATABASE_URL is required for PostgreSQL backup')
            cmd = [pg_dump, '--dbname=' + url, '--format=custom', '--file=' + str(dest)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise CommandError('pg_dump failed: ' + (proc.stderr or 'unknown error')[:500])
        else:
            raise CommandError(f'Unsupported database engine: {engine}')

        self.stdout.write(json.dumps({
            'ok': True, 'engine': engine, 'path': str(dest),
            'bytes': dest.stat().st_size,
        }, ensure_ascii=False))
