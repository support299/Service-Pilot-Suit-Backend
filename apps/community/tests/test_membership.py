"""Channel member add / remove / role management."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.community import services
from apps.community.models import CommunityChannel, CommunityChannelMember
from apps.rbac.constants import Permissions, Roles
from apps.rbac.services import seed_rbac
from apps.tenancy.models import Agency, Location, Membership

User = get_user_model()


class CommunityMembershipServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac()
        from apps.rbac.models import Role

        cls.agency = Agency.objects.create(ghl_company_id="co_mem", name="Mem Agency")
        cls.location_a = Location.objects.create(
            ghl_location_id="loc_mem_a",
            name="Location A",
            agency=cls.agency,
        )
        cls.location_b = Location.objects.create(
            ghl_location_id="loc_mem_b",
            name="Location B",
            agency=cls.agency,
        )
        cls.manager = User.objects.create_user(email="mgr_mem@example.com", password="x")
        cls.staff = User.objects.create_user(email="staff_mem@example.com", password="x")
        cls.staff_b = User.objects.create_user(email="staff_b@example.com", password="x")
        cls.agency_admin = User.objects.create_user(
            email="agency_mem@example.com", password="x"
        )
        cls.outsider = User.objects.create_user(
            email="outsider@example.com", password="x"
        )

        Membership.objects.create(
            user=cls.manager,
            location=cls.location_a,
            role=Role.objects.get(slug=Roles.MANAGER),
        )
        Membership.objects.create(
            user=cls.staff,
            location=cls.location_a,
            role=Role.objects.get(slug=Roles.STAFF),
        )
        Membership.objects.create(
            user=cls.agency_admin,
            location=cls.location_a,
            role=Role.objects.get(slug=Roles.AGENCY_ADMIN),
        )
        Membership.objects.create(
            user=cls.staff_b,
            location=cls.location_b,
            role=Role.objects.get(slug=Roles.STAFF),
        )
        Membership.objects.create(
            user=cls.outsider,
            location=cls.location_b,
            role=Role.objects.get(slug=Roles.STAFF),
        )

        services.ensure_platform_seeds()

    def _mgr_held(self) -> set[str]:
        return {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        }

    def _staff_held(self) -> set[str]:
        return {Permissions.COMMUNITY_VIEW, Permissions.COMMUNITY_POST}

    def _platform_held(self) -> set[str]:
        return {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
            Permissions.COMMUNITY_MANAGE_PLATFORM,
        }

    def _soft_leave(self, *, channel_id: str, user) -> None:
        CommunityChannelMember.objects.filter(
            channel_id=channel_id, user=user, left_at__isnull=True
        ).update(left_at=timezone.now())

    def _company_channel_without_staff(self) -> dict:
        """Create company channel then soft-remove staff so they become a candidate."""
        data = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            name="Crew Room",
            channel_type="company",
        )
        services.remove_channel_member(
            channel_id=data["id"],
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            target_user_id=str(self.staff.id),
        )
        return data

    def test_manager_adds_and_removes_company_member(self):
        channel = self._company_channel_without_staff()
        roster = services.list_members(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
        )
        self.assertTrue(roster["can_manage"])
        candidate_ids = {c["user_id"] for c in roster["candidates"]}
        self.assertIn(str(self.staff.id), candidate_ids)
        self.assertNotIn(str(self.staff_b.id), candidate_ids)

        added = services.add_channel_member(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            target_user_id=str(self.staff.id),
            role="moderator",
        )
        member_ids = {m["user"]["id"] for m in added["members"] if m.get("user")}
        self.assertIn(str(self.staff.id), member_ids)
        staff_row = next(
            m
            for m in added["members"]
            if m["user"] and m["user"]["id"] == str(self.staff.id)
        )
        self.assertEqual(staff_row["role"], "moderator")
        self.assertNotIn(
            str(self.staff.id), {c["user_id"] for c in added["candidates"]}
        )

        removed = services.remove_channel_member(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            target_user_id=str(self.staff.id),
        )
        self.assertNotIn(
            str(self.staff.id),
            {m["user"]["id"] for m in removed["members"] if m.get("user")},
        )
        row = CommunityChannelMember.objects.get(
            channel_id=channel["id"], user=self.staff
        )
        self.assertIsNotNone(row.left_at)

        readded = services.add_channel_member(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            target_user_id=str(self.staff.id),
            role="member",
        )
        self.assertIn(
            str(self.staff.id),
            {m["user"]["id"] for m in readded["members"] if m.get("user")},
        )
        row.refresh_from_db()
        self.assertIsNone(row.left_at)
        self.assertEqual(row.role, "member")

    def test_staff_cannot_manage_members(self):
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            name="Locked",
            channel_type="company",
        )
        roster = services.list_members(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.staff,
            held=self._staff_held(),
        )
        self.assertFalse(roster["can_manage"])
        self.assertEqual(roster["candidates"], [])

        with self.assertRaises(PermissionDeniedError):
            services.add_channel_member(
                channel_id=channel["id"],
                location=self.location_a,
                user=self.staff,
                held=self._staff_held(),
                target_user_id=str(self.manager.id),
                role="member",
            )

    def test_cross_location_add_denied(self):
        channel = self._company_channel_without_staff()
        with self.assertRaises(ValidationError):
            services.add_channel_member(
                channel_id=channel["id"],
                location=self.location_a,
                user=self.manager,
                held=self._mgr_held(),
                target_user_id=str(self.staff_b.id),
                role="member",
            )

    def test_location_manager_cannot_manage_platform_members(self):
        industry = CommunityChannel.objects.filter(
            channel_type=CommunityChannel.ChannelType.INDUSTRY,
            location__isnull=True,
        ).first()
        self.assertIsNotNone(industry)

        with self.assertRaises(PermissionDeniedError):
            services.add_channel_member(
                channel_id=str(industry.id),
                location=self.location_a,
                user=self.manager,
                held=self._mgr_held(),
                target_user_id=str(self.staff.id),
                role="member",
            )

        roster = services.list_members(
            channel_id=str(industry.id),
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
        )
        self.assertFalse(roster["can_manage"])
        self.assertEqual(roster["candidates"], [])

    def test_agency_admin_manages_platform_channel_members(self):
        industry = CommunityChannel.objects.filter(
            channel_type=CommunityChannel.ChannelType.INDUSTRY,
            location__isnull=True,
        ).first()
        self.assertIsNotNone(industry)

        self._soft_leave(channel_id=str(industry.id), user=self.staff)

        added = services.add_channel_member(
            channel_id=str(industry.id),
            location=self.location_a,
            user=self.agency_admin,
            held=self._platform_held(),
            target_user_id=str(self.staff.id),
            role="owner",
        )
        self.assertTrue(added["can_manage"])
        staff_row = next(
            m
            for m in added["members"]
            if m["user"] and m["user"]["id"] == str(self.staff.id)
        )
        self.assertEqual(staff_row["role"], "owner")

        updated = services.update_channel_member_role(
            channel_id=str(industry.id),
            location=self.location_a,
            user=self.agency_admin,
            held=self._platform_held(),
            target_user_id=str(self.staff.id),
            role="moderator",
        )
        staff_row = next(
            m
            for m in updated["members"]
            if m["user"] and m["user"]["id"] == str(self.staff.id)
        )
        self.assertEqual(staff_row["role"], "moderator")

        with self.assertRaises(ValidationError):
            services.add_channel_member(
                channel_id=str(industry.id),
                location=self.location_a,
                user=self.agency_admin,
                held=self._platform_held(),
                target_user_id=str(self.staff_b.id),
                role="member",
            )

    def test_cannot_self_remove(self):
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            name="Self Remove",
            channel_type="company",
        )
        with self.assertRaises(ValidationError):
            services.remove_channel_member(
                channel_id=channel["id"],
                location=self.location_a,
                user=self.manager,
                held=self._mgr_held(),
                target_user_id=str(self.manager.id),
            )

    def test_update_role_on_company_member(self):
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            name="Roles",
            channel_type="company",
        )
        updated = services.update_channel_member_role(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            target_user_id=str(self.staff.id),
            role="owner",
        )
        staff_row = next(
            m
            for m in updated["members"]
            if m["user"] and m["user"]["id"] == str(self.staff.id)
        )
        self.assertEqual(staff_row["role"], "owner")

    def test_remove_missing_member_404(self):
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=self._mgr_held(),
            name="Ghost",
            channel_type="company",
        )
        with self.assertRaises(NotFoundError):
            services.remove_channel_member(
                channel_id=channel["id"],
                location=self.location_a,
                user=self.manager,
                held=self._mgr_held(),
                target_user_id=str(self.outsider.id),
            )
