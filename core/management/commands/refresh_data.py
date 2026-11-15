"""Refresh cached NASA/external data — run via cron/Task Scheduler.

Usage:
    python manage.py refresh_data [--days 30]

Fetches POWER data for registered farmer fields and refreshes FAO cache.
Safe to run repeatedly — all services are cached.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Refresh cached external data (NASA POWER, FAO, CMR)'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args, **opts):
        from farmer.models import Field
        from core.services.nasa import fetch_power
        from core.services.fao import fetch_crop, CROPS
        from datetime import date, timedelta

        end = date.today()
        start = end - timedelta(days=opts['days'])
        s, e = start.strftime('%Y%m%d'), end.strftime('%Y%m%d')

        # refresh POWER for all fields with coords
        fields = Field.objects.exclude(lat__isnull=True).exclude(lon__isnull=True)
        ok = fail = 0
        for fl in fields:
            try:
                fetch_power(fl.lat, fl.lon, s, e,
                            ['T2M', 'PRECTOTCORR', 'RH2M', 'WS10M', 'ALLSKY_SFC_SW_DWN'],
                            community='AG', temporal='daily')
                ok += 1
            except Exception as ex:
                fail += 1
                self.stderr.write(f'field {fl.id}: {ex}')
        self.stdout.write(f'POWER: {ok} ok, {fail} failed')

        # refresh FAO crops
        ok = fail = 0
        for c in CROPS:
            try:
                fetch_crop(c['key'], refresh=True)
                ok += 1
            except Exception as ex:
                fail += 1
                self.stderr.write(f'crop {c["key"]}: {ex}')
        self.stdout.write(f'FAO: {ok} ok, {fail} failed')
