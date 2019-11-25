from rest_framework.decorators import api_view
from rest_framework.response import Response
from . import view_utils as utils
from django.db.models import Q
from frontend.models import PCT, Practice, STP, RegionalTeam, PCN


@api_view(["GET"])
def org_codes(request, format=None):
    org_codes = utils.param_to_list(request.query_params.get("q", None))
    org_types = utils.param_to_list(request.query_params.get("org_type", None))
    is_exact = request.GET.get("exact", "")
    if not org_types:
        org_types = [""]
    if not org_codes:
        org_codes = [""]
    data = []
    for org_code in org_codes:
        for org_type in org_types:
            data += _get_org_from_code(org_code, is_exact, org_type)
    return Response(data)


def _get_org_from_code(q, is_exact, org_type):
    org_type = _normalise_org_type(q, is_exact, org_type)
    if is_exact:
        return _get_org_from_code_exact(q, org_type)
    else:
        return _get_org_from_code_inexact(q, org_type)


def _get_org_from_code_exact(q, org_type):
    if org_type == "practice":
        results = Practice.objects.filter(Q(code=q) | Q(name=q))
        values = results.values("name", "code", "ccg")
        for v in values:
            v["id"] = v["code"]
            v["type"] = "practice"
        return values
    elif org_type == "ccg":
        results = PCT.objects.filter(Q(code=q) | Q(name=q)).filter(org_type="CCG")
        values = results.values("name", "code")
        for v in values:
            v["id"] = v["code"]
            v["type"] = "CCG"
        return values
    elif org_type == "pcn":
        return _get_pcns_like_code(q, is_exact=True)
    elif org_type == "stp":
        return _get_stps_like_code(q, is_exact=True)
    elif org_type == "regional_team":
        return _get_regional_teams_like_code(q, is_exact=True)
    else:
        raise ValueError("Unknown org_type: {}".format(org_type))


def _get_org_from_code_inexact(q, org_type):
    if org_type == "practice":
        return _get_practices_like_code(q)
    elif org_type == "ccg":
        return _get_pcts_like_code(q)
    elif org_type == "practice_or_ccg":
        return list(_get_pcts_like_code(q)) + _get_practices_like_code(q)
    elif org_type == "pcn":
        return _get_pcns_like_code(q)
    elif org_type == "stp":
        return _get_stps_like_code(q)
    elif org_type == "regional_team":
        return _get_regional_teams_like_code(q)
    else:
        raise ValueError("Unknown org_type: {}".format(org_type))


def _normalise_org_type(q, is_exact, org_type):
    """
    Replicate the vagaries of the old API implementation with respect to
    org_types
    """
    # If an org_type is supplied just use that (correcting the case for CCG)
    if org_type:
        if org_type == "CCG":
            org_type = "ccg"
        return org_type
    # Otherwise we determine the default based on the behaviour of the old API
    if is_exact:
        if len(q) == 3:
            return "ccg"
        else:
            return "practice"
    else:
        return "practice_or_ccg"


def _get_practices_like_code(q):
    if q:
        practices = Practice.objects.filter(
            Q(setting=4)
            & Q(status_code="A")
            & (
                Q(code__istartswith=q)
                | Q(name__icontains=q)
                | Q(postcode__istartswith=q)
            )
        ).order_by("name")
    else:
        practices = Practice.objects.all()
    results = []
    for p in practices:
        data = {
            "id": p.code,
            "code": p.code,
            "name": p.name,
            "postcode": p.postcode,
            "setting": p.setting,
            "setting_name": None,
            "type": "practice",
            "ccg": None,
        }
        data["setting_name"] = p.get_setting_display()
        if p.ccg:
            data["ccg"] = p.ccg.code
        results.append(data)
    return results


def _get_pcts_like_code(q):
    pcts = PCT.objects.filter(close_date__isnull=True)
    if q:
        pcts = pcts.filter(Q(code__istartswith=q) | Q(name__icontains=q)).filter(
            org_type="CCG"
        )
    pct_values = pcts.values("name", "code")
    for p in pct_values:
        p["id"] = p["code"]
        p["type"] = "CCG"
    return pct_values


def _get_pcns_like_code(q, is_exact=False):
    orgs = PCN.objects.active()
    if is_exact:
        orgs = orgs.filter(Q(ons_code=q) | Q(name=q))
    elif q:
        orgs = orgs.filter(Q(ons_code__istartswith=q) | Q(name__icontains=q))
    org_values = orgs.values("name", "ons_code")
    for org in org_values:
        org["code"] = org.pop("ons_code")
        org["id"] = org["code"]
        org["type"] = "pcn"
    return org_values


def _get_stps_like_code(q, is_exact=False):
    orgs = STP.objects.all()
    if is_exact:
        orgs = orgs.filter(Q(ons_code=q) | Q(name=q))
    elif q:
        orgs = orgs.filter(Q(ons_code__istartswith=q) | Q(name__icontains=q))
    org_values = orgs.values("name", "ons_code")
    for org in org_values:
        org["code"] = org.pop("ons_code")
        org["id"] = org["code"]
        org["type"] = "stp"
    return org_values


def _get_regional_teams_like_code(q, is_exact=False):
    orgs = RegionalTeam.objects.active()
    if is_exact:
        orgs = orgs.filter(Q(code=q) | Q(name=q))
    elif q:
        orgs = orgs.filter(Q(code__istartswith=q) | Q(name__icontains=q))
    org_values = orgs.values("name", "code")
    for org in org_values:
        org["id"] = org["code"]
        org["type"] = "regional_team"
    return org_values
