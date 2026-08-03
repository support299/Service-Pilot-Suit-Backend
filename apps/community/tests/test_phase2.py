"""Phase 2 tests — availability + cross-location DM denial + pins."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common.exceptions import PermissionDeniedError, ValidationError
from apps.community import services, services_availability, services_dms, services_pins
from apps.community.services_dms import CROSS_LOCATION_CODE
from apps.rbac.constants import Permissions, Roles
from apps.rbac.services import seed_rbac
from apps.tenancy.models import Agency, Location, Membership

User = get_user_model()


class CommunityPhase2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac()
        from apps.rbac.models import Role

        cls.agency = Agency.objects.create(ghl_company_id="co_p2", name="P2 Agency")
        cls.loc_a = Location.objects.create(
            ghl_location_id="loc_p2_a", name="Loc A", agency=cls.agency
        )
        cls.loc_b = Location.objects.create(
            ghl_location_id="loc_p2_b", name="Loc B", agency=cls.agency
        )
        cls.user_a = User.objects.create_user(email="a@p2.test", password="x")
        cls.user_b = User.objects.create_user(email="b@p2.test", password="x")
        cls.user_other_co = User.objects.create_user(email="other@p2.test", password="x")

        staff = Role.objects.get(slug=Roles.STAFF)
        manager = Role.objects.get(slug=Roles.MANAGER)
        Membership.objects.create(user=cls.user_a, location=cls.loc_a, role=manager)
        Membership.objects.create(user=cls.user_b, location=cls.loc_a, role=staff)
        Membership.objects.create(
            user=cls.user_other_co, location=cls.loc_b, role=staff
        )

        services.ensure_platform_seeds()
        cls.held = {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE,
        }

    def test_availability_roundtrip(self):
        data = services_availability.set_my_availability(
            location=self.loc_a,
            user=self.user_a,
            status="available",
            status_message="On site",
        )
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["status_message"], "On site")
        me = services_availability.get_my_availability(
            location=self.loc_a, user=self.user_a
        )
        self.assertEqual(me["status"], "available")

    def test_dm_same_location_ok(self):
        convo = services_dms.open_or_create_dm(
            location=self.loc_a,
            user=self.user_a,
            target_user_id=str(self.user_b.id),
        )
        self.assertEqual(convo["recipient"]["email"], "b@p2.test")
        msg = services_dms.create_dm_message(
            conversation_id=convo["id"],
            location=self.loc_a,
            user=self.user_a,
            body="Hey teammate",
        )
        self.assertEqual(msg["body"], "Hey teammate")
        listed = services_dms.list_dm_messages(
            conversation_id=convo["id"],
            location=self.loc_a,
            user=self.user_b,
        )
        self.assertEqual(len(listed["messages"]), 1)

    def test_dm_cross_location_denied(self):
        with self.assertRaises(PermissionDeniedError) as ctx:
            services_dms.open_or_create_dm(
                location=self.loc_a,
                user=self.user_a,
                target_user_id=str(self.user_other_co.id),
            )
        self.assertEqual(ctx.exception.code, CROSS_LOCATION_CODE)

    def test_industry_member_from_other_location_cannot_be_dm_from_here(self):
        """Even if both join an industry channel, DM still requires same location."""
        held_platform = {
            Permissions.COMMUNITY_VIEW,
            Permissions.COMMUNITY_POST,
            Permissions.COMMUNITY_MANAGE_PLATFORM,
        }
        # Agency-admin-style create industry channel via platform perm on loc A
        industry = (
            __import__("apps.community.models", fromlist=["CommunityChannel"])
            .CommunityChannel.objects.filter(channel_type="industry")
            .first()
        )
        self.assertIsNotNone(industry)
        # Both post into industry (auto-join)
        services.create_message(
            channel_id=str(industry.id),
            location=self.loc_a,
            user=self.user_a,
            held=self.held,
            body="From A",
        )
        services.create_message(
            channel_id=str(industry.id),
            location=self.loc_b,
            user=self.user_other_co,
            held={Permissions.COMMUNITY_VIEW, Permissions.COMMUNITY_POST},
            body="From B",
        )
        members = services.list_members(
            channel_id=str(industry.id),
            location=self.loc_a,
            user=self.user_a,
        )
        other_rows = [
            m
            for m in members["members"]
            if m["user"] and m["user"]["email"] == "other@p2.test"
        ]
        self.assertTrue(other_rows)
        self.assertFalse(other_rows[0]["can_dm"])

        with self.assertRaises(PermissionDeniedError) as ctx:
            services_dms.open_or_create_dm(
                location=self.loc_a,
                user=self.user_a,
                target_user_id=str(self.user_other_co.id),
            )
        self.assertEqual(ctx.exception.code, CROSS_LOCATION_CODE)

    def test_pin_limit(self):
        channel = services.create_channel(
            location=self.loc_a,
            user=self.user_a,
            held=self.held,
            name="Pin Lab",
            channel_type="company",
        )
        ids = []
        for i in range(5):
            m = services.create_message(
                channel_id=channel["id"],
                location=self.loc_a,
                user=self.user_a,
                held=self.held,
                body=f"pin {i}",
            )
            ids.append(m["id"])
            services_pins.pin_message(
                message_id=m["id"],
                location=self.loc_a,
                user=self.user_a,
                held=self.held,
            )
        extra = services.create_message(
            channel_id=channel["id"],
            location=self.loc_a,
            user=self.user_a,
            held=self.held,
            body="too many",
        )
        with self.assertRaises(ValidationError):
            services_pins.pin_message(
                message_id=extra["id"],
                location=self.loc_a,
                user=self.user_a,
                held=self.held,
            )

    def test_save_message(self):
        channel = services.create_channel(
            location=self.loc_a,
            user=self.user_a,
            held=self.held,
            name="Save Lab",
            channel_type="company",
        )
        msg = services.create_message(
            channel_id=channel["id"],
            location=self.loc_a,
            user=self.user_a,
            held=self.held,
            body="keep me",
        )
        services_pins.save_message(
            message_id=msg["id"], location=self.loc_a, user=self.user_b
        )
        saved = services_pins.list_saved(location=self.loc_a, user=self.user_b)
        self.assertEqual(saved["count"], 1)
        self.assertEqual(saved["saved"][0]["message"]["id"], msg["id"])
