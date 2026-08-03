"""Seed Service Pilot + Industry platform channels (idempotent by slug)."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.community.services import ensure_platform_seeds


class Command(BaseCommand):
    help = "Seed Community platform channels (SP Announcements/Integrations + industry groups)."

    def handle(self, *args, **options):
        result = ensure_platform_seeds()
        self.stdout.write(
            self.style.SUCCESS(
                f"Community seeds: created={result['created']} updated={result['updated']}"
            )
        )
