from django.core.management.base import BaseCommand

from apps.rbac.services import seed_rbac


class Command(BaseCommand):
    help = "Seed the default RBAC roles and permissions (idempotent)."

    def handle(self, *args, **options):
        seed_rbac()
        self.stdout.write(self.style.SUCCESS("RBAC roles and permissions seeded."))
