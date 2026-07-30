"""Tests for location-level membership permission hierarchy."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common.exceptions import PermissionDeniedError
from apps.rbac.constants import Permissions, Roles
from apps.rbac.models import Role
from apps.rbac.services import seed_rbac
from apps.tenancy.models import Agency, Location, Membership
from apps.tenancy.services.location_membership_permissions import (
    can_edit_location_membership_permissions,
    filter_enabled_for_actor,
    update_location_membership_permissions,
)

User = get_user_model()


class LocationMembershipPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac()
        cls.agency = Agency.objects.create(ghl_company_id="co_mem", name="Mem Agency")
        cls.location = Location.objects.create(
            ghl_location_id="loc_mem",
            name="Mem Location",
            agency=cls.agency,
        )
        cls.agency_admin_role = Role.objects.get(slug=Roles.AGENCY_ADMIN)
        cls.manager_role = Role.objects.get(slug=Roles.MANAGER)
        cls.staff_role = Role.objects.get(slug=Roles.STAFF)

        cls.agency_user = User.objects.create_user(email="aa@example.com", password="x")
        cls.manager = User.objects.create_user(email="mgr@example.com", password="x")
        cls.staff = User.objects.create_user(email="staff@example.com", password="x")
        cls.other_manager = User.objects.create_user(email="mgr2@example.com", password="x")

        cls.aa_m = Membership.objects.create(
            user=cls.agency_user, location=cls.location, role=cls.agency_admin_role
        )
        cls.mgr_m = Membership.objects.create(
            user=cls.manager, location=cls.location, role=cls.manager_role
        )
        cls.staff_m = Membership.objects.create(
            user=cls.staff, location=cls.location, role=cls.staff_role
        )
        cls.mgr2_m = Membership.objects.create(
            user=cls.other_manager, location=cls.location, role=cls.manager_role
        )

    def test_agency_admin_can_edit_all_non_super(self):
        self.assertTrue(
            can_edit_location_membership_permissions(
                actor=self.agency_user,
                actor_membership=self.aa_m,
                target=self.staff_m,
            )
        )
        self.assertTrue(
            can_edit_location_membership_permissions(
                actor=self.agency_user,
                actor_membership=self.aa_m,
                target=self.mgr_m,
            )
        )

    def test_manager_can_edit_managers_and_staff_not_agency_admin(self):
        self.assertTrue(
            can_edit_location_membership_permissions(
                actor=self.manager,
                actor_membership=self.mgr_m,
                target=self.staff_m,
            )
        )
        self.assertTrue(
            can_edit_location_membership_permissions(
                actor=self.manager,
                actor_membership=self.mgr_m,
                target=self.mgr2_m,
            )
        )
        self.assertFalse(
            can_edit_location_membership_permissions(
                actor=self.manager,
                actor_membership=self.mgr_m,
                target=self.aa_m,
            )
        )

    def test_staff_cannot_edit(self):
        self.assertFalse(
            can_edit_location_membership_permissions(
                actor=self.staff,
                actor_membership=self.staff_m,
                target=self.mgr_m,
            )
        )

    def test_manager_cannot_grant_agency_manage(self):
        filtered = filter_enabled_for_actor(
            actor=self.manager,
            actor_membership=self.mgr_m,
            enabled=[Permissions.SUPPORT_VIEW, Permissions.AGENCY_MANAGE],
        )
        self.assertIn(Permissions.SUPPORT_VIEW, filtered or [])
        self.assertNotIn(Permissions.AGENCY_MANAGE, filtered or [])

    def test_update_denied_for_manager_on_agency_admin(self):
        with self.assertRaises(PermissionDeniedError):
            update_location_membership_permissions(
                self.aa_m,
                actor=self.manager,
                actor_membership=self.mgr_m,
                enabled=[Permissions.SUPPORT_VIEW],
            )
