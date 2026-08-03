"""Community hub / channel service tests."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common.exceptions import PermissionDeniedError
from apps.community import services
from apps.community.models import CommunityChannel, CommunityChannelMember
from apps.rbac.constants import Permissions, Roles
from apps.rbac.services import seed_rbac
from apps.tenancy.models import Agency, Location, Membership

User = get_user_model()


class CommunityChannelServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac()
        from apps.rbac.models import Role

        cls.agency = Agency.objects.create(ghl_company_id="co_comm", name="Comm Agency")
        cls.location_a = Location.objects.create(
            ghl_location_id="loc_a",
            name="Location A",
            agency=cls.agency,
        )
        cls.location_b = Location.objects.create(
            ghl_location_id="loc_b",
            name="Location B",
            agency=cls.agency,
        )
        cls.manager = User.objects.create_user(email="mgr@example.com", password="x")
        cls.staff = User.objects.create_user(email="staff@example.com", password="x")
        cls.agency_admin = User.objects.create_user(
            email="agency@example.com", password="x"
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
            user=cls.staff,
            location=cls.location_b,
            role=Role.objects.get(slug=Roles.STAFF),
        )

        services.ensure_platform_seeds()

    def _held(self, *codes: str) -> set[str]:
        return set(codes)

    def test_manager_creates_company_channel_and_auto_joins_members(self):
        held = self._held(
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        )
        data = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=held,
            name="Technicians",
            description="Field crew",
            channel_type="company",
        )
        self.assertEqual(data["channel_type"], "company")
        self.assertEqual(data["location_id"], str(self.location_a.id))
        channel = CommunityChannel.objects.get(pk=data["id"])
        self.assertEqual(channel.location_id, self.location_a.id)
        # Manager + staff on location A both auto-joined.
        self.assertEqual(
            CommunityChannelMember.objects.filter(
                channel=channel, left_at__isnull=True
            ).count(),
            3,  # manager, staff, agency_admin all on location A
        )
        owner = CommunityChannelMember.objects.get(
            channel=channel, user=self.manager, left_at__isnull=True
        )
        self.assertEqual(owner.role, CommunityChannelMember.Role.OWNER)

    def test_staff_cannot_create_company_channel(self):
        held = self._held(Permissions.COMMUNITY_VIEW, Permissions.COMMUNITY_POST)
        with self.assertRaises(PermissionDeniedError):
            services.create_channel(
                location=self.location_a,
                user=self.staff,
                held=held,
                name="Nope",
                channel_type="company",
            )

    def test_manager_cannot_create_industry_without_platform_perm(self):
        held = self._held(
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        )
        with self.assertRaises(PermissionDeniedError):
            services.create_channel(
                location=self.location_a,
                user=self.manager,
                held=held,
                name="Secret Industry",
                channel_type="industry",
            )

    def test_agency_admin_creates_industry_channel(self):
        held = self._held(
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
            Permissions.COMMUNITY_MANAGE_PLATFORM,
        )
        data = services.create_channel(
            location=self.location_a,
            user=self.agency_admin,
            held=held,
            name="Custom Vertical",
            channel_type="industry",
        )
        self.assertEqual(data["channel_type"], "industry")
        self.assertIsNone(data["location_id"])

    def test_company_channels_isolated_by_location(self):
        held = self._held(
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        )
        created = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=held,
            name="A Only",
            channel_type="company",
        )
        hub_b = services.list_hub(
            location=self.location_b,
            user=self.staff,
            held={Permissions.COMMUNITY_VIEW, Permissions.COMMUNITY_POST},
        )
        company_ids = {c["id"] for c in hub_b["company"]["channels"]}
        self.assertNotIn(created["id"], company_ids)
        # Platform channels still visible from location B.
        self.assertGreaterEqual(hub_b["industry"]["count"], 1)
        self.assertGreaterEqual(hub_b["service_pilot"]["count"], 1)

    def test_hub_creatable_types_role_aware(self):
        manager_hub = services.list_hub(
            location=self.location_a,
            user=self.manager,
            held={
                Permissions.COMMUNITY_VIEW,
                Permissions.COMMUNITY_POST,
                Permissions.COMMUNITY_MANAGE,
            },
        )
        values = {t["value"] for t in manager_hub["meta"]["creatable_types"]}
        self.assertEqual(values, {"company"})

        admin_hub = services.list_hub(
            location=self.location_a,
            user=self.agency_admin,
            held={
                Permissions.COMMUNITY_VIEW,
                Permissions.COMMUNITY_POST,
                Permissions.COMMUNITY_MANAGE,
                Permissions.COMMUNITY_MANAGE_PLATFORM,
            },
        )
        admin_values = {t["value"] for t in admin_hub["meta"]["creatable_types"]}
        self.assertEqual(admin_values, {"company", "service_pilot", "industry"})

    def test_create_and_list_messages(self):
        held = {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        }
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=held,
            name="Chat Room",
            channel_type="company",
        )
        msg = services.create_message(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=held,
            body="Hello team",
        )
        self.assertEqual(msg["body"], "Hello team")
        self.assertEqual(msg["author"]["email"], "mgr@example.com")

        listed = services.list_messages(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.staff,
        )
        self.assertEqual(len(listed["messages"]), 1)
        self.assertEqual(listed["messages"][0]["id"], msg["id"])

    def test_cannot_post_to_archived_channel(self):
        from apps.common.exceptions import ValidationError

        held = {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        }
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=held,
            name="Soon Archived",
            channel_type="company",
        )
        services.archive_channel(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=held,
        )
        with self.assertRaises(ValidationError):
            services.create_message(
                channel_id=channel["id"],
                location=self.location_a,
                user=self.manager,
                held=held,
                body="Nope",
            )

    def test_company_messages_not_visible_other_location(self):
        from apps.common.exceptions import NotFoundError

        held = {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        }
        channel = services.create_channel(
            location=self.location_a,
            user=self.manager,
            held=held,
            name="Private A",
            channel_type="company",
        )
        services.create_message(
            channel_id=channel["id"],
            location=self.location_a,
            user=self.manager,
            held=held,
            body="Secret",
        )
        with self.assertRaises(NotFoundError):
            services.list_messages(
                channel_id=channel["id"],
                location=self.location_b,
                user=self.staff,
            )
