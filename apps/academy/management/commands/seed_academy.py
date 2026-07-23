"""Seed sample Academy courses for local/dev environments."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.academy.models import AcademyCourse, AcademyLesson


SAMPLE = [
    {
        "slug": "welcome-to-service-pilot",
        "title": "Welcome to The Service Pilot",
        "description": "A quick orientation to the Suite — where to find ROI, Support, and your team.",
        "body": "Start here if you're new. These short lessons walk through the core areas of the product.",
        "course_type": AcademyCourse.CourseType.ONBOARDING,
        "section_key": AcademyCourse.Section.GETTING_STARTED,
        "duration_minutes": 12,
        "featured": True,
        "sort_order": 10,
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "lessons": [
            {
                "title": "Your workspace at a glance",
                "description": "Sidebar, location switcher, and where each module lives.",
                "body": "Use the left sidebar to jump between Dashboard, ROI Center, and Success Center. The location switcher at the top scopes everything you see.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 4,
                "sort_order": 1,
            },
            {
                "title": "Switching locations",
                "description": "How multi-location teams stay organized.",
                "body": "Pick a location from the switcher. Tickets, ROI data, and Academy progress are tracked per location.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 3,
                "sort_order": 2,
            },
            {
                "title": "Getting help",
                "description": "Open a support ticket with screenshots when something looks wrong.",
                "body": "Success Center → Support. Attach photos or short videos so we can resolve issues faster.",
                "lesson_type": AcademyLesson.LessonType.VIDEO,
                "duration_minutes": 5,
                "sort_order": 3,
                "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
        ],
    },
    {
        "slug": "roi-center-basics",
        "title": "ROI Center basics",
        "description": "Read Meta and Google ad performance without leaving the Suite.",
        "body": "Learn how spend, clicks, and conversions show up after you connect ads through GoHighLevel.",
        "course_type": AcademyCourse.CourseType.COURSE,
        "section_key": AcademyCourse.Section.COURSES,
        "duration_minutes": 18,
        "featured": True,
        "sort_order": 20,
        "lessons": [
            {
                "title": "Overview tab",
                "description": "Combined spend and the big KPIs.",
                "body": "The Overview tab rolls up Facebook and Google into one view. Use the date range to compare periods.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 6,
                "sort_order": 1,
            },
            {
                "title": "Facebook & Google tabs",
                "description": "Drill into each platform.",
                "body": "Open Facebook or Google for campaign-level detail. Sync pulls fresh numbers from GHL Ad Publishing into your database.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 7,
                "sort_order": 2,
            },
            {
                "title": "When numbers look off",
                "description": "Sync timing and what to check first.",
                "body": "Hit Sync, confirm the location token is healthy, then compare the same window in GHL. Open a Support ticket with a screenshot if they still disagree.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 3,
            },
        ],
    },
    {
        "slug": "support-best-practices",
        "title": "Support best practices",
        "description": "Write tickets that get resolved faster.",
        "body": "Short guide for customers and team members who file issues.",
        "course_type": AcademyCourse.CourseType.KNOWLEDGE_BASE,
        "section_key": AcademyCourse.Section.KNOWLEDGE_BASE,
        "duration_minutes": 8,
        "sort_order": 30,
        "lessons": [
            {
                "title": "What to include",
                "description": "Subject, steps, expected vs actual, and media.",
                "body": "One clear subject. Steps to reproduce. What you expected vs what happened. Attach a screenshot or screen recording when the UI is involved.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 4,
                "sort_order": 1,
            },
            {
                "title": "Statuses explained",
                "description": "Open, waiting on you, waiting on SP, resolved.",
                "body": "When we need more info the ticket moves to Waiting on you. Reply to bounce it back to our team.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 4,
                "sort_order": 2,
            },
        ],
    },
    {
        "slug": "how-to-use-members",
        "title": "Invite and manage your team",
        "description": "Roles, permissions, and who can see what.",
        "body": "A practical walkthrough of Members for location owners.",
        "course_type": AcademyCourse.CourseType.COURSE,
        "section_key": AcademyCourse.Section.HOW_TO,
        "duration_minutes": 10,
        "sort_order": 40,
        "lessons": [
            {
                "title": "Roles at a glance",
                "description": "Read-only through agency admin.",
                "body": "Read Only can view. Staff can manage Support and reports. Managers handle people. Agency Admin owns the org.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 1,
            },
            {
                "title": "Adding someone",
                "description": "Invite flow and location access.",
                "body": "From Members, invite by email and pick a role. They only see locations you grant.",
                "lesson_type": AcademyLesson.LessonType.ARTICLE,
                "duration_minutes": 5,
                "sort_order": 2,
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Seed sample Academy courses and lessons (idempotent by slug)."

    def handle(self, *args, **options):
        now = timezone.now()
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
            for lesson in item["lessons"]:
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
                    for k, v in defaults.items():
                        setattr(existing, k, v)
                    existing.save()
                else:
                    AcademyLesson.objects.create(course=course, title=lesson["title"], **defaults)

        self.stdout.write(
            self.style.SUCCESS(
                f"Academy seed done. courses_created={created_courses} total={AcademyCourse.objects.count()}"
            )
        )
