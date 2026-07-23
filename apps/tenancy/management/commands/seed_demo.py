"""Seed a demo tenant so the app is usable without a live GHL install.

Creates: RBAC catalog, a demo agency + two locations, and a set of demo users
(one per role) with memberships. Safe to run repeatedly.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.rbac.constants import Roles
from apps.rbac.services import get_role, seed_rbac
from apps.tenancy.services import ProvisioningService

User = get_user_model()

DEMO_AGENCY = ("demo-company-001", "Northwind Services Group")
DEMO_LOCATIONS = [
    ("demo-location-001", "Northwind — Downtown"),
    ("demo-location-002", "Northwind — Westside"),
]
DEMO_USERS = [
    ("owner@northwind.test", "Alex", "Rivera", Roles.AGENCY_ADMIN),
    ("manager@northwind.test", "Sam", "Okafor", Roles.MANAGER),
    ("staff@northwind.test", "Jordan", "Lee", Roles.STAFF),
    ("viewer@northwind.test", "Priya", "Nair", Roles.READ_ONLY),
]


class Command(BaseCommand):
    help = "Seed RBAC + a demo agency, locations, users and memberships."

    def add_arguments(self, parser):
        parser.add_argument(
            "--superuser-email",
            default="admin@servicepilot.test",
            help="Email for the demo superuser.",
        )
        parser.add_argument(
            "--superuser-password",
            default="admin12345",
            help="Password for the demo superuser.",
        )

    def handle(self, *args, **options):
        seed_rbac()
        self.stdout.write(self.style.SUCCESS("• RBAC seeded"))

        agency = ProvisioningService.upsert_agency(
            company_id=DEMO_AGENCY[0], name=DEMO_AGENCY[1]
        )
        locations = [
            ProvisioningService.upsert_location(
                location_id=loc_id, name=name, agency=agency, timezone_name="UTC"
            )
            for loc_id, name in DEMO_LOCATIONS
        ]
        self.stdout.write(self.style.SUCCESS(f"• Agency + {len(locations)} locations"))

        for email, first, last, role_slug in DEMO_USERS:
            user, _ = ProvisioningService.get_or_create_user(
                email=email, defaults={"first_name": first, "last_name": last}
            )
            role = get_role(role_slug)
            for location in locations:
                ProvisioningService.assign_membership(
                    user=user, location=location, role=role
                )
        self.stdout.write(self.style.SUCCESS(f"• {len(DEMO_USERS)} demo users + memberships"))

        su_email = options["superuser_email"].strip().lower()
        su = User.objects.filter(email=su_email).first()
        if su is None:
            su = User.objects.create_superuser(
                email=su_email, password=options["superuser_password"]
            )
            self.stdout.write(self.style.SUCCESS(f"• Superuser created: {su_email}"))
        else:
            self.stdout.write(f"• Superuser already exists: {su_email}")

        self.stdout.write(self.style.SUCCESS("\nDemo seed complete."))
        self.stdout.write("Try auto-login with:")
        self.stdout.write("  email=owner@northwind.test  location_id=demo-location-001")
