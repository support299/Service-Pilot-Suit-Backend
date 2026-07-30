"""Feature Center service-layer tests."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common.exceptions import ValidationError
from apps.feature import services
from apps.feature.models import (
    FeatureReleaseNote,
    FeatureRequest,
    FeatureStatusEvent,
    FeatureVote,
)
from apps.rbac.constants import Permissions, Roles
from apps.rbac.services import seed_rbac
from apps.tenancy.models import Agency, Location, Membership

User = get_user_model()


class FeatureCenterServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac()
        cls.agency = Agency.objects.create(ghl_company_id="co_test", name="Test Agency")
        cls.location = Location.objects.create(
            ghl_location_id="loc_test",
            name="Test Location",
            agency=cls.agency,
        )
        cls.user = User.objects.create_user(email="voter@example.com", password="x")
        cls.other = User.objects.create_user(email="other@example.com", password="x")
        cls.admin = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )
        from apps.rbac.models import Role

        staff_role = Role.objects.get(slug=Roles.STAFF)
        Membership.objects.create(
            user=cls.user, location=cls.location, role=staff_role
        )
        Membership.objects.create(
            user=cls.other, location=cls.location, role=staff_role
        )

    def _create(self, **kwargs):
        defaults = {
            "location": self.location,
            "user": self.user,
            "title": "Export ROI CSV",
            "description": "Allow owners to export ROI tables.",
            "category": FeatureRequest.Category.ROI_CENTER,
        }
        defaults.update(kwargs)
        return services.create_feature_request(**defaults)

    def test_create_feature_request(self):
        data = self._create()
        self.assertEqual(data["status"], "submitted")
        self.assertEqual(data["category"], "roi_center")
        self.assertEqual(FeatureStatusEvent.objects.count(), 1)
        fr = FeatureRequest.objects.get(pk=data["id"])
        self.assertEqual(fr.source_location_id, self.location.id)
        self.assertEqual(fr.source_agency_id, self.agency.id)

    def test_vote_and_remove_vote(self):
        data = self._create()
        rid = data["id"]
        voted = services.add_vote(request_id=rid, user=self.user)
        self.assertTrue(voted["has_voted"])
        self.assertEqual(voted["vote_count"], 1)

        # Duplicate vote is idempotent
        again = services.add_vote(request_id=rid, user=self.user)
        self.assertEqual(again["vote_count"], 1)
        self.assertEqual(FeatureVote.objects.filter(feature_request_id=rid).count(), 1)

        services.add_vote(request_id=rid, user=self.other)
        after = services.get_feature_detail(rid, user=self.user)
        self.assertEqual(after["vote_count"], 2)

        removed = services.remove_vote(request_id=rid, user=self.user)
        self.assertFalse(removed["has_voted"])
        self.assertEqual(removed["vote_count"], 1)

    def test_duplicate_vote_constraint(self):
        data = self._create()
        services.add_vote(request_id=data["id"], user=self.user)
        # Second create should not raise to caller; service swallows IntegrityError
        services.add_vote(request_id=data["id"], user=self.user)
        self.assertEqual(
            FeatureVote.objects.filter(feature_request_id=data["id"]).count(), 1
        )

    def test_status_transition_and_event(self):
        data = self._create()
        rid = data["id"]
        updated = services.update_status(
            request_id=rid,
            user=self.admin,
            status="under_review",
        )
        self.assertEqual(updated["status"], "under_review")
        self.assertEqual(FeatureStatusEvent.objects.filter(feature_request_id=rid).count(), 2)

        with self.assertRaises(ValidationError):
            services.update_status(
                request_id=rid, user=self.admin, status="released"
            )

    def test_released_locks_votes(self):
        data = self._create()
        rid = data["id"]
        for status in ("under_review", "planned", "in_progress", "testing", "released"):
            services.update_status(request_id=rid, user=self.admin, status=status)

        with self.assertRaises(ValidationError):
            services.add_vote(request_id=rid, user=self.user)

    def test_customer_detail_hides_internal_comments_and_source(self):
        data = self._create()
        rid = data["id"]
        services.add_internal_comment(
            request_id=rid, user=self.admin, body="Internal note"
        )
        services.add_public_comment(
            request_id=rid, user=self.user, body="Public discussion"
        )
        customer = services.get_feature_detail(rid, user=self.user, include_staff=False)
        self.assertNotIn("internal_comments", customer)
        self.assertNotIn("source", customer)
        self.assertEqual(len(customer["comments"]), 1)
        self.assertEqual(customer["comments"][0]["body"], "Public discussion")
        self.assertNotIn("email", customer["comments"][0]["author"] or {})

        staff = services.get_feature_detail(rid, user=self.admin, include_staff=True)
        self.assertEqual(len(staff["internal_comments"]), 1)
        self.assertEqual(len(staff["comments"]), 1)
        self.assertIn("source", staff)

    def test_public_comment_locked_when_released(self):
        data = self._create()
        rid = data["id"]
        for status in ("under_review", "planned", "in_progress", "testing", "released"):
            services.update_status(request_id=rid, user=self.admin, status=status)
        with self.assertRaises(ValidationError):
            services.add_public_comment(
                request_id=rid, user=self.user, body="Too late"
            )

    def test_release_note_publish_visibility(self):
        data = self._create()
        rid = data["id"]
        draft = services.create_release_note(
            user=self.admin,
            title="Draft note",
            body="Hidden",
            request_id=rid,
            publish=False,
        )
        self.assertEqual(draft["status"], "draft")

        published_list = services.list_published_announcements()
        self.assertEqual(published_list["count"], 0)

        services.publish_release_note(note_id=draft["id"], user=self.admin)
        published_list = services.list_published_announcements()
        self.assertEqual(published_list["count"], 1)

        services.archive_release_note(note_id=draft["id"], user=self.admin)
        published_list = services.list_published_announcements()
        self.assertEqual(published_list["count"], 0)
        note = FeatureReleaseNote.objects.get(pk=draft["id"])
        self.assertEqual(note.status, "archived")

    def test_list_filter_and_sort(self):
        self._create(title="ROI idea", category="roi_center")
        self._create(
            title="Members idea",
            description="Invite flow",
            category="members",
            user=self.other,
        )
        listed = services.list_feature_requests(
            user=self.user, category="members", sort="newest"
        )
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["results"][0]["category"], "members")

    def test_feature_manage_not_on_staff_role_defaults(self):
        from apps.rbac.constants import DEFAULT_ROLE_PERMISSIONS

        self.assertIn(Permissions.FEATURE_VIEW, DEFAULT_ROLE_PERMISSIONS[Roles.STAFF])
        self.assertNotIn(
            Permissions.FEATURE_MANAGE, DEFAULT_ROLE_PERMISSIONS[Roles.STAFF]
        )
        self.assertNotIn(
            Permissions.FEATURE_MANAGE, DEFAULT_ROLE_PERMISSIONS[Roles.AGENCY_ADMIN]
        )
        self.assertIn(
            Permissions.FEATURE_MANAGE, DEFAULT_ROLE_PERMISSIONS[Roles.SUPER_ADMIN]
        )
