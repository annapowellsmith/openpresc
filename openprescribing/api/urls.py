from django.conf.urls import url
from rest_framework.urlpatterns import format_suffix_patterns
from . import views_bnf_codes
from . import views_spending
from . import views_org_codes
from . import views_org_details
from . import views_org_location
from . import views_measures


urlpatterns = [
    url(r"^spending/$", views_spending.total_spending, name="total_spending"),
    url(r"^bubble/$", views_spending.bubble, name="bubble"),
    url(r"^tariff/$", views_spending.tariff, name="tariff_api"),
    url(
        r"^spending_by_ccg/$",
        views_spending.spending_by_org,
        name="spending_by_ccg",
        kwargs={"org_type": "ccg"},
    ),
    url(
        r"^spending_by_practice/$",
        views_spending.spending_by_org,
        name="spending_by_practice",
        kwargs={"org_type": "practice"},
    ),
    url(r"^spending_by_org/$", views_spending.spending_by_org, name="spending_by_org"),
    url(r"^measure/$", views_measures.measure_global, name="measure"),
    url(r"^measure_by_stp/$", views_measures.measure_by_stp, name="measure_by_stp"),
    url(
        r"^measure_by_regional_team/$",
        views_measures.measure_by_regional_team,
        name="measure_by_regional_team",
    ),
    url(r"^measure_by_ccg/$", views_measures.measure_by_ccg, name="measure_by_ccg"),
    url(r"^measure_by_pcn/$", views_measures.measure_by_pcn, name="measure_by_pcn"),
    url(
        r"^measure_numerators_by_org/$",
        views_measures.measure_numerators_by_org,
        name="measure_numerators_by_org",
    ),
    url(
        r"^measure_by_practice/$",
        views_measures.measure_by_practice,
        name="measure_by_practice",
    ),
    url(r"^price_per_unit/$", views_spending.price_per_unit, name="price_per_unit_api"),
    url(r"^ghost_generics/$", views_spending.ghost_generics, name="ghost_generics_api"),
    url(r"^org_details/$", views_org_details.org_details),
    url(r"^bnf_code/$", views_bnf_codes.bnf_codes),
    url(r"^org_code/$", views_org_codes.org_codes),
    url(r"^org_location/$", views_org_location.org_location, name="org_location"),
]

urlpatterns = format_suffix_patterns(urlpatterns, allowed=["json", "csv"])
