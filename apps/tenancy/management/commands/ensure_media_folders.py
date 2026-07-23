"""Backfill GHL media folders for existing locations."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.tenancy.models import Location
from apps.tenancy.services.ghl_media import ensure_location_onboard_media_folders


class Command(BaseCommand):
    help = "Ensure onboard media folders (e.g. Support Media) exist in GHL for each location."

    def add_arguments(self, parser):
        parser.add_argument(
            "--location",
            dest="location_id",
            default="",
            help="Optional GHL location id to limit the run.",
        )

    def handle(self, *args, **options):
        qs = Location.objects.select_related("agency").filter(is_active=True)
        loc_id = (options.get("location_id") or "").strip()
        if loc_id:
            qs = qs.filter(ghl_location_id=loc_id)

        ok = 0
        err = 0
        for location in qs:
            try:
                folders = ensure_location_onboard_media_folders(location)
                if not folders:
                    raise RuntimeError("no folders returned")
                self.stdout.write(
                    self.style.SUCCESS(f"{location.ghl_location_id}: {folders}")
                )
                ok += 1
            except Exception as exc:
                err += 1
                self.stderr.write(
                    self.style.ERROR(f"{location.ghl_location_id}: {exc}")
                )
        self.stdout.write(self.style.NOTICE(f"Done. ok={ok} errors={err}"))
