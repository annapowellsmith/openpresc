import functools

from django.conf.urls import include
from django.urls import path
from django.urls import reverse
from django.views.generic import RedirectView, TemplateView
from django.contrib import admin
from django.http.response import HttpResponseRedirect
from frontend.views import views

admin.autodiscover()

handler500 = views.custom_500


# Added 2018-11-15: maybe revist in a year to see if still required
def redirect_if_tags_query(view_fn):
    """
    Redirect CCG/practice homepage requests if they have a "tags" query
    parameter

    We need this because these homepages used to show all measures which could
    be filtered by tag, but that content has since moved to the
    measures_for_one_X pages. Internal links have been updated but there are
    links which we don't control.
    """

    @functools.wraps(view_fn)
    def wrapper(request, **kwargs):
        if not request.GET.get("tags"):
            return view_fn(request, **kwargs)
        if "ccg_code" in kwargs:
            url = reverse("measures_for_one_ccg", kwargs=kwargs)
        else:
            url = reverse(
                "measures_for_one_practice",
                kwargs={"practice_code": kwargs["practice_code"]},
            )
        url = "{}?{}".format(url, request.GET.urlencode())
        return HttpResponseRedirect(url)

    return wrapper


def all_england_redirects(request, *args, **kwargs):
    url = request.get_full_path().replace("/all-england/", "/national/england/")
    return HttpResponseRedirect(url)


urlpatterns = [
    # Static pages.
    path(r"", TemplateView.as_view(template_name="index.html"), name="home"),
    path(r"api/", TemplateView.as_view(template_name="api.html"), name="api"),
    path(r"about/", TemplateView.as_view(template_name="about.html"), name="about"),
    path(r"faq/", TemplateView.as_view(template_name="faq.html"), name="faq"),
    path(
        r"long_term_trends/",
        TemplateView.as_view(template_name="long_term_trends.html"),
        name="long_term_trends",
    ),
    path(
        r"price-per-unit-faq/",
        TemplateView.as_view(template_name="price_per_unit_faq.html"),
        name="price_per_unit_faq",
    ),
    path(
        r"privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy"
    ),
    path(
        r"contact/", TemplateView.as_view(template_name="contact.html"), name="contact"
    ),
    path(r"feedback/", views.feedback_view, name="feedback"),
    path(
        r"how-to-use/",
        TemplateView.as_view(template_name="how-to-use.html"),
        name="how-to-use",
    ),
    path(
        r"alert_example/",
        TemplateView.as_view(template_name="alert_example.html"),
        name="alert_example",
    ),
    path(
        r"research/",
        TemplateView.as_view(template_name="research.html"),
        name="research",
    ),
    path(r"500/", views.error, name="error"),
    path(r"ping/", views.ping, name="ping"),
    ##################################################
    # User-facing pages.
    ##################################################
    # BNF sections
    path(r"bnf/", views.all_bnf, name="all_bnf"),
    path(r"bnf/<section_id>/", views.bnf_section, name="bnf_section"),
    # Chemicals
    path(r"chemical/", views.all_chemicals, name="all_chemicals"),
    path(r"chemical/<bnf_code>/", views.chemical, name="chemical"),
    # GP practices
    path(r"practice/", views.all_practices, name="all_practices"),
    path(
        r"practice/<practice_code>/",
        redirect_if_tags_query(views.practice_home_page),
        name="practice_home_page",
    ),
    # PCNs
    path(r"pcn/", views.all_pcns, name="all_pcns"),
    path(r"pcn/<pcn_code>/", views.pcn_home_page, name="pcn_home_page"),
    # CCGs
    path(r"ccg/", views.all_ccgs, name="all_ccgs"),
    path(
        r"ccg/<ccg_code>/",
        redirect_if_tags_query(views.ccg_home_page),
        name="ccg_home_page",
    ),
    # STPs
    path(r"stp/", views.all_stps, name="all_stps"),
    path(r"stp/<stp_code>/", views.stp_home_page, name="stp_home_page"),
    # Regional teams
    path(r"regional-team/", views.all_regional_teams, name="all_regional_teams"),
    path(
        r"regional-team/<regional_team_code>/",
        views.regional_team_home_page,
        name="regional_team_home_page",
    ),
    # All England
    path(r"national/england/", views.all_england, name="all_england"),
    path(r"all-england/", all_england_redirects),
    path(
        r"hospitals/",
        TemplateView.as_view(template_name="all_hospitals.html"),
        name="hospitals",
    ),
    # Analyse
    path(r"analyse/", views.analyse, name="analyse"),
    # Price per unit
    # This must come above measures, as the measure_for_practices_in_ccg
    # pattern would also match the ccg_price_per_unit pattern.
    path(
        r"practice/<code>/price_per_unit/",
        views.practice_price_per_unit,
        name="practice_price_per_unit",
    ),
    path(
        r"ccg/<code>/price_per_unit/",
        views.ccg_price_per_unit,
        name="ccg_price_per_unit",
    ),
    path(
        r"national/england/price-per-unit/",
        views.all_england_price_per_unit,
        name="all_england_price_per_unit",
    ),
    path(r"all-england/price-per-unit/", all_england_redirects),
    path(
        r"practice/<entity_code>/<bnf_code>/price_per_unit/",
        views.price_per_unit_by_presentation,
        name="price_per_unit_by_presentation_practice",
    ),
    path(
        r"ccg/<entity_code>/<bnf_code>/price_per_unit/",
        views.price_per_unit_by_presentation,
        name="price_per_unit_by_presentation",
    ),
    path(
        r"national/england/<bnf_code>/price-per-unit/",
        views.all_england_price_per_unit_by_presentation,
        name="all_england_price_per_unit_by_presentation",
    ),
    path(r"all-england/<bnf_code>/price-per-unit/", all_england_redirects),
    # Ghost generics
    path(
        r"practice/<code>/ghost_generics/",
        views.ghost_generics_for_entity,
        name="practice_ghost_generics",
        kwargs={"entity_type": "practice"},
    ),
    path(
        r"ccg/<code>/ghost_generics/",
        views.ghost_generics_for_entity,
        name="ccg_ghost_generics",
        kwargs={"entity_type": "CCG"},
    ),
    # Spending
    # (This must go above Measures because of the measure_for_practices_in_ccg
    # pattern)
    path(
        r"practice/<entity_code>/concessions/",
        views.spending_for_one_entity,
        name="spending_for_one_practice",
        kwargs={"entity_type": "practice"},
    ),
    path(
        r"pcn/<entity_code>/concessions/",
        views.spending_for_one_entity,
        name="spending_for_one_pcn",
        kwargs={"entity_type": "pcn"},
    ),
    path(
        r"ccg/<entity_code>/concessions/",
        views.spending_for_one_entity,
        name="spending_for_one_ccg",
        kwargs={"entity_type": "CCG"},
    ),
    path(
        r"stp/<entity_code>/concessions/",
        views.spending_for_one_entity,
        name="spending_for_one_stp",
        kwargs={"entity_type": "stp"},
    ),
    path(
        r"regional-team/<entity_code>/concessions/",
        views.spending_for_one_entity,
        name="spending_for_one_regional_team",
        kwargs={"entity_type": "regional_team"},
    ),
    path(
        r"national/england/concessions/",
        views.spending_for_one_entity,
        name="spending_for_all_england",
        kwargs={"entity_type": "all_england", "entity_code": None},
    ),
    path(r"all-england/concessions/", all_england_redirects),
    # Measures
    path(r"measure/", views.all_measures, name="all_measures"),
    path(
        r"measure/<measure>/practice/<entity_code>/",
        views.measure_for_one_entity,
        name="measure_for_one_practice",
        kwargs={"entity_type": "practice"},
    ),
    path(
        r"measure/<measure>/pcn/<entity_code>/",
        views.measure_for_one_entity,
        name="measure_for_one_pcn",
        kwargs={"entity_type": "pcn"},
    ),
    path(
        r"measure/<measure>/ccg/<entity_code>/",
        views.measure_for_one_entity,
        name="measure_for_one_ccg",
        kwargs={"entity_type": "ccg"},
    ),
    path(
        r"measure/<measure>/stp/<entity_code>/",
        views.measure_for_one_entity,
        name="measure_for_one_stp",
        kwargs={"entity_type": "stp"},
    ),
    path(
        r"measure/<measure>/regional-team/<entity_code>/",
        views.measure_for_one_entity,
        name="measure_for_one_regional_team",
        kwargs={"entity_type": "regional_team"},
    ),
    path(
        r"measure/<measure>/national/england/",
        views.measure_for_all_england,
        name="measure_for_all_england",
    ),
    path(r"measure/<measure>/all-england/", all_england_redirects),
    path(
        r"practice/<practice_code>/measures/",
        views.measures_for_one_practice,
        name="measures_for_one_practice",
    ),
    path(
        r"pcn/<pcn_code>/measures/",
        views.measures_for_one_pcn,
        name="measures_for_one_pcn",
    ),
    path(
        r"ccg/<ccg_code>/measures/",
        views.measures_for_one_ccg,
        name="measures_for_one_ccg",
    ),
    path(
        r"stp/<stp_code>/measures/",
        views.measures_for_one_stp,
        name="measures_for_one_stp",
    ),
    path(
        r"regional-team/<regional_team_code>/measures/",
        views.measures_for_one_regional_team,
        name="measures_for_one_regional_team",
    ),
    path(
        r"pcn/<pcn_code>/<measure>/",
        views.measure_for_practices_in_pcn,
        name="measure_for_practices_in_pcn",
    ),
    path(
        r"ccg/<ccg_code>/<measure>/",
        views.measure_for_practices_in_ccg,
        name="measure_for_practices_in_ccg",
    ),
    path(
        r"stp/<stp_code>/<measure>/",
        views.measure_for_ccgs_in_stp,
        name="measure_for_ccgs_in_stp",
    ),
    path(
        r"regional-team/<regional_team_code>/<measure>/",
        views.measure_for_ccgs_in_regional_team,
        name="measure_for_ccgs_in_regional_team",
    ),
    path(
        r"measure/<measure>/",
        views.measure_for_all_entities,
        name="measure_for_all_ccgs",
        kwargs={"entity_type": "ccg"},
    ),
    path(
        r"measure/<measure>/definition/",
        views.measure_definition,
        name="measure_definition",
    ),
    path(
        r"measure/<measure>/pcn/",
        views.measure_for_all_entities,
        name="measure_for_all_pcns",
        kwargs={"entity_type": "pcn"},
    ),
    path(
        r"measure/<measure>/stp/",
        views.measure_for_all_entities,
        name="measure_for_all_stps",
        kwargs={"entity_type": "stp"},
    ),
    path(
        r"measure/<measure>/regional-team/",
        views.measure_for_all_entities,
        name="measure_for_all_regional_teams",
        kwargs={"entity_type": "regional_team"},
    ),
    # Tariffs
    path(r"tariff/", views.tariff, name="tariff_index"),
    path(r"tariff/<code>/", views.tariff, name="tariff"),
    # DM+D
    path(r"dmd/", include("dmd.urls")),
    # API
    path(r"api/1.0/", include("api.urls")),
    # Docs
    path(r"docs/<doc_id>/", views.gdoc_view, name="docs"),
    # Other files.
    path(
        r"robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
    ),
    path(r"admin/", admin.site.urls),
    # bookmarks
    path(r"bookmarks/<key>/", views.bookmarks, name="bookmarks"),
    # anymail webhooks
    path(r"anymail/", include("anymail.urls")),
    # Redirects
    path(
        r"pca/", RedirectView.as_view(permanent=True, pattern_name="long_term_trends")
    ),
    path(r"caution/", RedirectView.as_view(pattern_name="faq", permanent=True)),
    # Wrong URL got published
    path(
        r"measures/", RedirectView.as_view(pattern_name="all_measures", permanent=True)
    ),
    # Temporary, for tracking letter mailouts. Should change to
    # redirect post March 2018
    path(
        r"<ccg_code>/", views.measures_for_one_ccg, name="measures_for_one_ccg_tracking"
    ),
]
