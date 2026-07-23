from django.urls import path

from .admin_views import (
    AcademyAdminCourseDetailView,
    AcademyAdminCourseListCreateView,
    AcademyAdminCoursePublishView,
    AcademyAdminLessonDetailView,
    AcademyAdminLessonListCreateView,
    AcademyAdminMetaView,
)
from .views import (
    AcademyCourseDetailView,
    AcademyCourseListView,
    AcademyLessonDetailView,
    AcademyProgressView,
    AcademySavedListCreateView,
    AcademySummaryView,
)

urlpatterns = [
    path("academy/summary/", AcademySummaryView.as_view(), name="academy-summary"),
    path("academy/courses/", AcademyCourseListView.as_view(), name="academy-course-list"),
    path(
        "academy/courses/<uuid:course_id>/",
        AcademyCourseDetailView.as_view(),
        name="academy-course-detail",
    ),
    path(
        "academy/lessons/<uuid:lesson_id>/",
        AcademyLessonDetailView.as_view(),
        name="academy-lesson-detail",
    ),
    path("academy/progress/", AcademyProgressView.as_view(), name="academy-progress"),
    path("academy/saved/", AcademySavedListCreateView.as_view(), name="academy-saved"),
    # Agency portal — catalog admin
    path(
        "agency/academy/meta/",
        AcademyAdminMetaView.as_view(),
        name="agency-academy-meta",
    ),
    path(
        "agency/academy/courses/",
        AcademyAdminCourseListCreateView.as_view(),
        name="agency-academy-courses",
    ),
    path(
        "agency/academy/courses/<uuid:course_id>/",
        AcademyAdminCourseDetailView.as_view(),
        name="agency-academy-course-detail",
    ),
    path(
        "agency/academy/courses/<uuid:course_id>/status/",
        AcademyAdminCoursePublishView.as_view(),
        name="agency-academy-course-status",
    ),
    path(
        "agency/academy/courses/<uuid:course_id>/lessons/",
        AcademyAdminLessonListCreateView.as_view(),
        name="agency-academy-lessons",
    ),
    path(
        "agency/academy/lessons/<uuid:lesson_id>/",
        AcademyAdminLessonDetailView.as_view(),
        name="agency-academy-lesson-detail",
    ),
]
