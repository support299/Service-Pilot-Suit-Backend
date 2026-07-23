from django.urls import path

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
]
