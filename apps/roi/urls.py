from django.urls import path

from .views import (
    CrmOpportunityListView,
    CrmOpportunitySyncView,
    CrmReturnsSummaryView,
    CrmSetupView,
    GoogleCampaignsView,
    GoogleDailyView,
    GoogleSummaryView,
    GoogleSyncView,
    MetaCampaignsView,
    MetaDailyView,
    MetaSummaryView,
    MetaSyncView,
)

urlpatterns = [
    path("roi/meta/summary/", MetaSummaryView.as_view(), name="roi-meta-summary"),
    path("roi/meta/daily/", MetaDailyView.as_view(), name="roi-meta-daily"),
    path("roi/meta/campaigns/", MetaCampaignsView.as_view(), name="roi-meta-campaigns"),
    path("roi/meta/sync/", MetaSyncView.as_view(), name="roi-meta-sync"),
    path("roi/google/summary/", GoogleSummaryView.as_view(), name="roi-google-summary"),
    path("roi/google/daily/", GoogleDailyView.as_view(), name="roi-google-daily"),
    path(
        "roi/google/campaigns/",
        GoogleCampaignsView.as_view(),
        name="roi-google-campaigns",
    ),
    path("roi/google/sync/", GoogleSyncView.as_view(), name="roi-google-sync"),
    path("roi/crm/setup/", CrmSetupView.as_view(), name="roi-crm-setup"),
    path("roi/crm/returns/", CrmReturnsSummaryView.as_view(), name="roi-crm-returns"),
    path(
        "roi/crm/opportunities/",
        CrmOpportunityListView.as_view(),
        name="roi-crm-opportunities",
    ),
    path(
        "roi/crm/opportunities/sync/",
        CrmOpportunitySyncView.as_view(),
        name="roi-crm-opportunities-sync",
    ),
]
