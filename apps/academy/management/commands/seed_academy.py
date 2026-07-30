"""Seed Academy courses for Success Center (idempotent by course slug)."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.academy.models import AcademyCourse, AcademyLesson


SAMPLE = [
    {
        "slug": "welcome-to-service-pilot-suite",
        "title": "Welcome to Service Pilot Suite",
        "description": "Orientation for new locations — shell, modules, and how GHL opens the app.",
        "body": (
            "Service Pilot Suite is the operations hub for your GoHighLevel sub-accounts. "
            "Open it from a GHL custom menu link and you land already signed in for that location."
        ),
        "course_type": AcademyCourse.CourseType.ONBOARDING,
        "section_key": AcademyCourse.Section.GETTING_STARTED,
        "duration_minutes": 15,
        "featured": True,
        "sort_order": 10,
        "lessons": [
            {
                "title": "What Suite includes",
                "description": "ROI Center, Success Center, Members, Locations, and Agency view.",
                "body": (
                    "Use the left sidebar to move between modules:\n\n"
                    "• Dashboard — quick pulse for the active location\n"
                    "• ROI Center — Facebook + Google ads and CRM ROAS\n"
                    "• Success Center — Academy learning, Support tickets, and Feature Center\n"
                    "• Members & Locations — who can access this sub-account\n"
                    "• Agency view (Agency Admin) — company-wide people, locations, Academy admin\n\n"
                    "Everything you see is scoped to the location in the switcher (or Agency view)."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 1,
            },
            {
                "title": "Opening from GoHighLevel",
                "description": "Custom menu links with email + location_id.",
                "body": (
                    "In GHL, point custom menu links at Suite with query params so users auto-login:\n\n"
                    "https://suit.theservicepilot.com/?email={{user.email}}&location_id={{location.id}}\n\n"
                    "Optional chrome-less embed for ROI or Success:\n"
                    "…/roi?embed=1&email={{user.email}}&location_id={{location.id}}\n\n"
                    "If login says the location is not onboarded, install/onboard the Suite app "
                    "for that sub-account first."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 2,
            },
            {
                "title": "Switching locations",
                "description": "Multi-location teams stay organized.",
                "body": (
                    "The location switcher sets the active tenant. Tickets, ROI sync data, "
                    "opportunity ROAS, and Academy progress are all stored per location. "
                    "Agency Admins can open Agency view to manage the whole company."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 3,
            },
        ],
    },
    {
        "slug": "roi-center-ads-and-roas",
        "title": "ROI Center: ads, sync, and CRM ROAS",
        "description": "Read Facebook and Google performance, pick a pipeline, and sync opportunities.",
        "body": (
            "ROI Center stores ad metrics from GoHighLevel Ad Publishing and opportunity returns "
            "from your chosen CRM pipeline so you can compare spend vs won revenue."
        ),
        "course_type": AcademyCourse.CourseType.COURSE,
        "section_key": AcademyCourse.Section.COURSES,
        "duration_minutes": 25,
        "featured": True,
        "sort_order": 20,
        "lessons": [
            {
                "title": "Overview, Facebook, and Google tabs",
                "description": "Where totals and charts come from.",
                "body": (
                    "Overview combines Facebook + Google for the selected date range. "
                    "Facebook and Google tabs show platform KPIs, daily charts, and campaigns.\n\n"
                    "Numbers come from Suite’s database after Sync (or Celery). "
                    "Click Sync now to pull the visible range from GHL."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 6,
                "sort_order": 1,
            },
            {
                "title": "CRM pipeline for ROAS",
                "description": "Select a pipeline and Sync opportunities.",
                "body": (
                    "Under CRM pipeline for ROAS, choose the GHL pipeline that represents "
                    "your sales process, then Save & sync.\n\n"
                    "Suite stores opportunities for that pipeline only. Later Create / Update / "
                    "Delete / Stage webhooks keep them fresh. Manual Sync opportunities "
                    "is still available for a full refresh.\n\n"
                    "Won / open / lost revenue on each ads tab is matched by lead source "
                    "(Facebook vs Google vs other)."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 8,
                "sort_order": 2,
            },
            {
                "title": "Campaign tables — what to expect",
                "description": "Google has spend columns; Facebook catalog may not.",
                "body": (
                    "Google campaign rows include spend, clicks, and conversions for the last "
                    "synced range (GHL returns metrics on the Google list API).\n\n"
                    "Facebook campaign list from GHL is often catalog-only (name, status, id). "
                    "Account-level Facebook spend still appears in KPIs and charts from daily reporting. "
                    "Per-campaign Facebook spend depends on GHL’s campaign reporting API."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 3,
            },
            {
                "title": "When numbers look wrong",
                "description": "Checklist before opening Support.",
                "body": (
                    "1. Confirm the correct location is selected\n"
                    "2. Sync the same date range you see in GHL Ad Reporting\n"
                    "3. Confirm Meta/Google are connected under GHL Integrations for that location\n"
                    "4. For ROAS, confirm the pipeline is saved and opportunities have sources set\n"
                    "5. Open Success Center → Support with a screenshot if they still disagree"
                ),
                "lesson_type": AcademyLesson.LessonType.CHECKLIST,
                "duration_minutes": 6,
                "sort_order": 4,
            },
        ],
    },
    {
        "slug": "success-center-support",
        "title": "Success Center: Support tickets",
        "description": "File clear tickets with media so The Service Pilot can help faster.",
        "body": "Support lives in Success Center alongside Academy.",
        "course_type": AcademyCourse.CourseType.KNOWLEDGE_BASE,
        "section_key": AcademyCourse.Section.KNOWLEDGE_BASE,
        "duration_minutes": 10,
        "sort_order": 30,
        "lessons": [
            {
                "title": "What to include in a ticket",
                "description": "Subject, steps, expected vs actual, attachments.",
                "body": (
                    "Use one clear subject. Describe steps to reproduce. "
                    "Say what you expected vs what happened. Attach screenshots or short videos "
                    "from Support Media when the UI is involved."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 1,
            },
            {
                "title": "Ticket statuses",
                "description": "Open, waiting on you, waiting on SP, resolved.",
                "body": (
                    "When we need more info, the ticket moves to Waiting on you. "
                    "Reply in-thread to send it back. Resolved means the issue is closed; "
                    "re-open or create a new ticket if it returns."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 2,
            },
        ],
    },
    {
        "slug": "agency-portal-people-access",
        "title": "Agency portal: people and access",
        "description": "Company-wide locations, roles, and permission overrides.",
        "body": (
            "Agency Admins open Agency view to manage every connected location and who can "
            "enter the Agency portal."
        ),
        "course_type": AcademyCourse.CourseType.COURSE,
        "section_key": AcademyCourse.Section.HOW_TO,
        "duration_minutes": 18,
        "featured": True,
        "sort_order": 40,
        "lessons": [
            {
                "title": "Locations and onboard",
                "description": "See connected sub-accounts and onboard new ones.",
                "body": (
                    "The Locations tab lists active Suite locations for your company. "
                    "Use Onboard location to run GHL Marketplace OAuth for another sub-account. "
                    "Uninstalling the app in GHL deactivates that location in Suite."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 1,
            },
            {
                "title": "People & access",
                "description": "Memberships synced from GHL users.",
                "body": (
                    "People are created when a location is onboarded (GHL users/search) and when "
                    "UserCreate / UserUpdate / UserDelete webhooks fire.\n\n"
                    "Each row is a membership: user + location + role "
                    "(Agency Admin, Manager, Staff, Read Only)."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 6,
                "sort_order": 2,
            },
            {
                "title": "Permission overrides",
                "description": "Grant or deny extras per membership.",
                "body": (
                    "Open Permissions on a person to toggle grants and denies on top of their role. "
                    "agency.view controls who can open Agency view — Managers/Staff do not get it "
                    "by default unless you grant it."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 7,
                "sort_order": 3,
            },
        ],
    },
    {
        "slug": "academy-for-your-team",
        "title": "Academy for your team",
        "description": "How learners use Academy vs how Agency Admins publish courses.",
        "body": "Academy is the learning catalog inside Success Center.",
        "course_type": AcademyCourse.CourseType.COURSE,
        "section_key": AcademyCourse.Section.COURSES,
        "duration_minutes": 12,
        "sort_order": 50,
        "lessons": [
            {
                "title": "Learning as a location user",
                "description": "Browse, open lessons, track progress, save for later.",
                "body": (
                    "In Success Center → Academy, open a course, work through lessons, "
                    "and mark progress. Saved items stay on your list for this location."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 1,
            },
            {
                "title": "Publishing as Agency Admin",
                "description": "Courses and lessons from Agency → Academy.",
                "body": (
                    "Agency view → Academy admin lets you create courses/lessons, add Loom or "
                    "YouTube (share URL or embed HTML), and publish. "
                    "Published content appears for all locations in the catalog."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 7,
                "sort_order": 2,
            },
        ],
    },
    {
        "slug": "roles-and-who-sees-what",
        "title": "Roles and who sees what",
        "description": "Agency Admin, Manager, Staff, and Read Only in plain language.",
        "body": "Roles come from GHL user type/admin flags and can be adjusted in Agency People.",
        "course_type": AcademyCourse.CourseType.KNOWLEDGE_BASE,
        "section_key": AcademyCourse.Section.KNOWLEDGE_BASE,
        "duration_minutes": 8,
        "sort_order": 60,
        "lessons": [
            {
                "title": "Default role mapping",
                "description": "How GHL users map into Suite roles.",
                "body": (
                    "• GHL agency users → Agency Admin\n"
                    "• Location admin → Manager\n"
                    "• Everyone else → Staff\n\n"
                    "Only Agency Admin gets agency.view by default. Use permission toggles "
                    "if someone else needs Agency portal access."
                ),
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 8,
                "sort_order": 1,
            },
        ],
    },
]


# Keep old slugs updated so prior seeds refresh instead of orphaning.
LEGACY_SLUG_ALIASES = {
    "welcome-to-service-pilot": "welcome-to-service-pilot-suite",
    "roi-center-basics": "roi-center-ads-and-roas",
    "support-best-practices": "success-center-support",
    "how-to-use-members": "agency-portal-people-access",
}


class Command(BaseCommand):
    help = "Seed Academy courses and lessons for Success Center (idempotent by slug)."

    def handle(self, *args, **options):
        now = timezone.now()
        # Soft-retire renamed sample courses so catalogs stay clean.
        for old_slug, new_slug in LEGACY_SLUG_ALIASES.items():
            if AcademyCourse.objects.filter(slug=new_slug).exists():
                AcademyCourse.objects.filter(slug=old_slug).update(
                    status=AcademyCourse.Status.ARCHIVED
                )

        created_courses = 0
        for item in SAMPLE:
            slug = item["slug"]
            course, was_created = AcademyCourse.objects.update_or_create(
                slug=slug,
                defaults={
                    "title": item["title"],
                    "description": item["description"],
                    "body": item["body"],
                    "course_type": item["course_type"],
                    "section_key": item["section_key"],
                    "status": AcademyCourse.Status.PUBLISHED,
                    "duration_minutes": item["duration_minutes"],
                    "sort_order": item["sort_order"],
                    "featured": item.get("featured", False),
                    "video_url": item.get("video_url", ""),
                    "published_at": now,
                },
            )
            if was_created:
                created_courses += 1

            keep_titles: set[str] = set()
            for lesson in item["lessons"]:
                keep_titles.add(lesson["title"])
                existing = course.lessons.filter(title=lesson["title"]).first()
                defaults = {
                    "description": lesson["description"],
                    "body": lesson["body"],
                    "lesson_type": lesson["lesson_type"],
                    "status": AcademyLesson.Status.PUBLISHED,
                    "duration_minutes": lesson["duration_minutes"],
                    "sort_order": lesson["sort_order"],
                    "video_url": lesson.get("video_url", ""),
                }
                if existing:
                    for key, value in defaults.items():
                        setattr(existing, key, value)
                    existing.save()
                else:
                    AcademyLesson.objects.create(
                        course=course, title=lesson["title"], **defaults
                    )

            # Drop lessons removed from the seed for this course.
            course.lessons.exclude(title__in=keep_titles).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Academy seed done. courses_created={created_courses} "
                f"published={AcademyCourse.objects.filter(status='published').count()}"
            )
        )
