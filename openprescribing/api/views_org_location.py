import api.view_utils as utils
from api.geojson_serializer import as_geojson_stream
from django.contrib.gis.db.models.aggregates import Union
from django.db.models import F, Q
from django.http import HttpResponse
from frontend.models import PCN, PCT, STP, Practice, RegionalTeam
from rest_framework.decorators import api_view


@api_view(["GET"])
def org_location(request, format=None):
    # We make practice the default org type for compatibility with the previous
    # API
    org_type = request.GET.get("org_type", "practice")
    centroids = request.GET.get("centroids", "")
    org_codes = utils.param_to_list(request.GET.get("q", ""))
    if org_type == "practice":
        results = _get_practices(org_codes, centroids)
    elif org_type == "ccg":
        results = _get_ccgs(org_codes, centroids)
    elif org_type == "pcn":
        results = _get_pcns(org_codes, centroids)
    elif org_type == "stp":
        results = _get_stps(org_codes, centroids)
    elif org_type == "regional_team":
        results = _get_regional_teams(org_codes, centroids)
    else:
        raise ValueError("Unknown org_type: {}".format(org_type))
    return HttpResponse(as_geojson_stream(results), content_type="application/json")


def _get_practices(org_codes, centroids):
    org_codes = utils.get_practice_ids_from_org(org_codes)
    results = Practice.objects.filter(code__in=org_codes)
    return results.values("name", "code", "setting", geometry=F("location"))


def _get_ccgs(org_codes, centroids):
    results = PCT.objects.filter(close_date__isnull=True, org_type="CCG")
    if org_codes:
        results = results.filter(code__in=org_codes)
    return results.values(
        "name",
        "code",
        "ons_code",
        "org_type",
        geometry=F("centroid" if centroids else "boundary"),
    )


def _get_pcns(org_codes, centroids):
    results = PCN.objects.active()
    if org_codes:
        results = results.filter(
            Q(code__in=org_codes) | Q(practice__ccg_id__in=org_codes)
        )
    return results.values("name", "code", geometry=Union("practice__boundary"))


def _get_stps(org_codes, centroids):
    results = STP.objects.all()
    if org_codes:
        results = results.filter(code__in=org_codes)
    return results.values("name", "code", geometry=Union("pct__boundary"))


def _get_regional_teams(org_codes, centroids):
    results = RegionalTeam.objects.active()
    if org_codes:
        results = results.filter(code__in=org_codes)
    return results.values("name", "code", geometry=Union("pct__boundary"))
