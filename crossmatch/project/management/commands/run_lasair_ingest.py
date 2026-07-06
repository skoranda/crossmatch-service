from django.core.management.base import BaseCommand
from brokers.lasair.consumer import consume_alerts
from core.metrics import start_metrics_server


class Command(BaseCommand):
    help = "Run Lasair alert ingest"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Lasair alert ingest...'))
        start_metrics_server()
        consume_alerts()
