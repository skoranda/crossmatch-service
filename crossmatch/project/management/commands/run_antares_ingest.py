from django.core.management.base import BaseCommand
from brokers.antares.consumer import consume_alerts
from core.metrics import start_metrics_server


class Command(BaseCommand):
    help = "Run ANTARES alert ingest"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Processing alerts...')
        )
        start_metrics_server()
        consume_alerts()
