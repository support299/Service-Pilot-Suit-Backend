from django.urls import path

from .views import (
    TicketDetailView,
    TicketListCreateView,
    TicketMessageCreateView,
    TicketStatusView,
    TicketSummaryView,
)

urlpatterns = [
    path("support/tickets/summary/", TicketSummaryView.as_view(), name="support-ticket-summary"),
    path("support/tickets/", TicketListCreateView.as_view(), name="support-ticket-list"),
    path(
        "support/tickets/<uuid:ticket_id>/",
        TicketDetailView.as_view(),
        name="support-ticket-detail",
    ),
    path(
        "support/tickets/<uuid:ticket_id>/status/",
        TicketStatusView.as_view(),
        name="support-ticket-status",
    ),
    path(
        "support/tickets/<uuid:ticket_id>/messages/",
        TicketMessageCreateView.as_view(),
        name="support-ticket-messages",
    ),
]
