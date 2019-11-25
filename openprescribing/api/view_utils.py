import itertools
from django.db import connection
from django.shortcuts import get_object_or_404


def param_to_list(str):
    params = []
    if str:
        params = str.split(",")
        params = [_f for _f in params if _f]
    return params


def dictfetchall(cursor):
    desc = cursor.description
    return [dict(zip([col[0] for col in desc], row)) for row in cursor.fetchall()]


def execute_query(query, params):
    cursor = connection.cursor()
    if isinstance(params, dict):
        cursor.execute(query, params)
    elif params:
        cursor.execute(query, tuple(itertools.chain.from_iterable(params)))
    else:
        cursor.execute(query)
    data = dictfetchall(cursor)
    cursor.close()
    return data


def get_practice_ids_from_org(org_codes):
    # Convert CCG codes to lists of practices.
    from frontend.models import Practice

    practices = []
    for i, org in enumerate(org_codes):
        if len(org) == 3:
            practices_for_ccg = Practice.objects.filter(ccg_id=org)
            for p in practices_for_ccg:
                practices.append(p.code)
        else:
            practices.append(org)
    return practices


def get_bnf_codes_from_number_str(codes):
    # Convert BNF strings (3.4, 3) to BNF codes (0304, 03).
    from frontend.models import Section

    converted = []
    for code in codes:
        if "." in code:
            section = get_object_or_404(Section, number_str=code)
            converted.append(section.bnf_id)
        elif len(code) < 3:
            section = get_object_or_404(Section, bnf_chapter=code, bnf_section=None)
            converted.append(section.bnf_id)
        else:
            # it's a presentation, not a section
            converted.append(code)
    return converted
