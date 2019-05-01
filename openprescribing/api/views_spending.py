import datetime
import re

from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import APIException

from common.utils import namedtuplefetchall
from common.utils import nhs_titlecase
from common.utils import ppu_sql
from frontend.models import GenericCodeMapping
from frontend.models import ImportLog
from frontend.models import Presentation
from frontend.models import Practice, PCT
from matrixstore.db import get_db, group_by

import view_utils as utils
from view_utils import db_timeout, BnfHierarchy


CODE_LENGTH_ERROR = (
    'Error: BNF Codes must all be the same length if written in the same '
    'search box. For example, you cannot search for Cerazette_Tab 75mcg '
    '(0703021Q0BBAAAA) and Cerelle (0703021Q0BD), but you could search for '
    'Cerazette (0703021Q0BB) and Cerelle (0703021Q0BD). If you need this '
    'data, please <a href="mailto:{{ SUPPORT_TO_EMAIL }}" '
    'class="feedback-show">get in touch</a> and we may be able to extract it '
    'for you')
MIN_GHOST_GENERIC_DELTA = 5


class NotValid(APIException):
    status_code = 400
    default_detail = 'The code you provided is not valid'


def _valid_or_latest_date(date):
    if date:
        try:
            date = datetime.datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise NotValid("%s is not a valid date" % date)
    else:
        date = ImportLog.objects.latest_in_category('prescribing').current_at
    return date


def _build_conditions_and_patterns(code, focus):
    if not re.match(r'[A-Z0-9]{15}', code):
        raise NotValid("%s is not a valid code" % code)

    # flatten and uniquify the list of codes
    extra_codes = set()
    for mapping in GenericCodeMapping.objects.filter(
        Q(from_code=code) | Q(to_code=code)
    ):
        extra_codes.add(mapping.from_code)
        extra_codes.add(mapping.to_code)

    patterns = ["%s____%s" % (code[:9], code[13:15])]
    for extra_code in extra_codes:
        if extra_code.endswith('%'):
            pattern = extra_code
        else:
            pattern = "%s____%s" % (extra_code[:9], extra_code[13:15])
        patterns.append(pattern)
    conditions = " OR ".join(["presentation_code LIKE %s "] * len(patterns))
    conditions = "AND (%s) " % conditions
    if focus:
        if len(focus) == 3:
            conditions += "AND (pct_id = %s)"
        else:
            conditions += "AND (practice_id = %s)"
        patterns.append(focus)
    return conditions, patterns


def _get_org_or_404(org_code, org_type=None):
    if not org_type and org_code:
        org_type = 'ccg' if len(org_code) == 3 else 'practice'
    if org_type.lower() == 'ccg':
        org = get_object_or_404(PCT, pk=org_code)
    elif org_type == 'practice':
        org = get_object_or_404(Practice, pk=org_code)
    else:
        raise ValueError(org_type)
    return org


@api_view(['GET'])
def bubble(request, format=None):
    """Returns data relating to price-per-unit, in a format suitable for
    use in Highcharts bubble chart.

    """
    code = request.query_params.get('bnf_code', '')
    trim = request.query_params.get('trim', '')
    date = _valid_or_latest_date(request.query_params.get('date', None))
    highlight = request.query_params.get('highlight', None)
    focus = request.query_params.get('focus', None) and highlight
    conditions, patterns = _build_conditions_and_patterns(code, focus)
    rounded_ppus_cte_sql = (
        "WITH rounded_ppus AS (SELECT presentation_code, "
        "COALESCE(frontend_presentation.name, 'unknown') "
        "AS presentation_name, "
        "quantity, net_cost, practice_id, pct_id, "
        "ROUND(CAST(net_cost/NULLIF(quantity, 0) AS numeric), 2) AS ppu "
        "FROM frontend_prescription "
        "LEFT JOIN frontend_presentation "
        "ON frontend_prescription.presentation_code = "
        "frontend_presentation.bnf_code "
        "LEFT JOIN frontend_practice ON frontend_practice.code = practice_id "
        "WHERE processing_date = %s "
        "AND setting = 4 " +
        conditions +
        ") "
    )
    binned_ppus_sql = rounded_ppus_cte_sql + (
        ", binned_ppus AS (SELECT presentation_code, presentation_name, ppu, "
        "SUM(quantity) AS quantity "
        "FROM rounded_ppus "
        "GROUP BY presentation_code, presentation_name, ppu) "
    )
    if trim:
        # Skip items where PPU is outside <trim> percentile (where
        # <trim> is out of 100)
        trim = float(trim)
        out_of = 100
        while trim % 1 != 0:
            trim = trim * 10
            out_of = out_of * 10
        ordered_ppus_sql = binned_ppus_sql + (
            "SELECT * FROM ("
            " SELECT *, "
            " SUM(ppu * quantity) OVER (PARTITION BY presentation_code)"
            "  / SUM(quantity) OVER (PARTITION BY presentation_code)"
            "      AS mean_ppu, "
            " NTILE(%s) OVER (ORDER BY ppu) AS ntiled "
            " FROM binned_ppus "
            " ORDER BY mean_ppu, presentation_name) ranked "
            "WHERE ntiled <= %s" % (out_of, trim)
        )
    else:

        ordered_ppus_sql = binned_ppus_sql + (
            "SELECT *, "
            "SUM(ppu * quantity) OVER (PARTITION BY presentation_code) "
            " / SUM(quantity) OVER (PARTITION BY presentation_code)"
            "     AS mean_ppu "
            "FROM binned_ppus "
            "ORDER BY mean_ppu, presentation_name, ppu"
        )
    mean_ppu_for_entity_sql = rounded_ppus_cte_sql + (
        "SELECT SUM(net_cost)/SUM(quantity) FROM rounded_ppus "
    )
    params = [date] + patterns
    with connection.cursor() as cursor:
        cursor.execute(ordered_ppus_sql, params)
        series = []
        categories = []
        pos = 0
        for result in namedtuplefetchall(cursor):
            if result.presentation_name not in [x['name'] for x in categories]:
                pos += 1
                is_generic = False
                if result.presentation_code[9:11] == 'AA':
                    is_generic = True
                categories.append(
                    {
                        'name': result.presentation_name,
                        'is_generic': is_generic
                    }
                )

            series.append({
                'x': pos,
                'y': result.ppu,
                'z': result.quantity,
                'mean_ppu': result.mean_ppu,
                'name': result.presentation_name})
        if highlight:
            params.append(highlight)
            if len(highlight) == 3:
                mean_ppu_for_entity_sql += "WHERE pct_id = %s "
            else:
                mean_ppu_for_entity_sql += "WHERE practice_id = %s "
        cursor.execute(mean_ppu_for_entity_sql, params)
        plotline = cursor.fetchone()[0]
        return Response(
            {'plotline': plotline, 'series': series, 'categories': categories})


@api_view(['GET'])
def price_per_unit(request, format=None):
    """Returns price per unit data for presentations and practices or
    CCGs

    """
    entity_code = request.query_params.get('entity_code')
    entity_type = request.query_params.get('entity_type')
    date = request.query_params.get('date')
    bnf_code = request.query_params.get('bnf_code')
    aggregate = bool(request.query_params.get('aggregate'))
    if not date:
        raise NotValid("You must supply a date")
    if not (entity_code or bnf_code or aggregate):
        raise NotValid(
            "You must supply a value for entity_code or bnf_code, or set the "
            "aggregate flag"
        )

    params = {'date': date}
    filename = date

    if bnf_code:
        params['bnf_code'] = bnf_code
        get_object_or_404(Presentation, pk=bnf_code)
        filename += "-%s" % bnf_code

    if entity_code:
        entity = _get_org_or_404(entity_code, entity_type)
        params['entity_code'] = entity_code
        filename += "-%s" % entity_code
        if not entity_type:
            if isinstance(entity, PCT):
                entity_type = 'CCG'
            else:
                entity_type = 'practice'

    extra_conditions = ""

    if bnf_code:
        extra_conditions += '''
        AND {ppusavings_table}.bnf_code = %(bnf_code)s'''

    if entity_code:
        if isinstance(entity, Practice):
            extra_conditions += '''
        AND {ppusavings_table}.practice_id = %(entity_code)s'''
        else:
            extra_conditions += '''
        AND {ppusavings_table}.pct_id = %(entity_code)s'''

            if bnf_code:
                extra_conditions += '''
        AND {ppusavings_table}.practice_id IS NOT NULL'''
            else:
                extra_conditions += '''
        AND {ppusavings_table}.practice_id IS NULL'''
    else:
        if entity_type == 'practice':
            extra_conditions += '''
                AND {ppusavings_table}.practice_id IS NOT NULL'''
        elif entity_type == 'CCG':
            extra_conditions += '''
                AND {ppusavings_table}.practice_id IS NULL'''

    sql = ppu_sql(conditions=extra_conditions)

    if aggregate:
        sql = _aggregate_ppu_sql(sql, entity_type)

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        results = utils.dictfetchall(cursor)

    for result in results:
        if result['practice_name'] is not None:
            result['practice_name'] = nhs_titlecase(result['practice_name'])
        if result['pct_name'] is not None:
            result['pct_name'] = nhs_titlecase(result['pct_name'])

    response = Response(results)
    if request.accepted_renderer.format == 'csv':
        filename = "%s-ppd.csv" % (filename)
        response['content-disposition'] = "attachment; filename=%s" % filename
    return response


@api_view(['GET'])
def ghost_generics(request, format=None):
    """Returns price per unit data for presentations and practices or
    CCGs

    """
    # We compare the price that should have been paid for a generic,
    # with the price actually paid. The price that should have been
    # paid comes from the Drug Tariff; however, we can't use that data
    # reliably because the BSA use an internal copy that doesn't match
    # with the published version (see #1318 for an explanation).
    #
    # Therefore, we use the median price paid nationally as a proxy
    # for the Drug Tariff price, which is computed and stored in the
    # materialized view `vw__medians_for_tariff` (only contains data
    # for current month; updated as part of the pipeline).
    #
    # We exclude trivial amounts of saving on the grounds these should
    # be actionable savings.
    date = request.query_params.get('date')
    entity_code = request.query_params.get('entity_code')
    entity_type = request.query_params.get('entity_type')
    group_by = request.query_params.get('group_by')
    entity = _get_org_or_404(entity_code, org_type=entity_type)
    if not date:
        raise NotValid("You must supply a date")

    params = {'date': date, 'entity_code': entity_code}
    filename = "ghost-generics-%s-%s" % (entity_code, date)
    extra_conditions = ""
    if isinstance(entity, Practice):
        extra_conditions += '  AND practice_id = %(entity_code)s'
    elif isinstance(entity, PCT):
        extra_conditions += '  AND ccg_id = %(entity_code)s'
    else:
        assert False, "Not implemented for {}".format(entity)
    sql = """
       WITH savings AS (
         SELECT dt.date,
            practice.code AS practice_id,
            practice.ccg_id AS pct,
            dt.median_ppu,
                CASE
                    WHEN rx.quantity > 0::double precision THEN round((rx.net_cost / rx.quantity)::numeric, 4)
                    ELSE 0
                END AS price_per_unit,
            rx.quantity,
            rx.presentation_code AS bnf_code,
            product.name AS product_name,
            rx.net_cost - round(dt.median_ppu::numeric, 4)::double precision * rx.quantity AS possible_savings
           FROM vw__medians_for_tariff dt
             JOIN dmd_product product ON dt.product_id = product.dmdid
             JOIN frontend_prescription rx ON rx.processing_date = dt.date AND rx.presentation_code = product.bnf_code
             JOIN frontend_practice practice ON practice.code = rx.practice_id
          WHERE rx.processing_date = %(date)s {extra_conditions}
        )
        SELECT *
          FROM savings s
         WHERE s.bnf_code::text <> '1106000L0AAAAAA'
         AND (s.possible_savings >= {min_delta} OR s.possible_savings <= -{min_delta})
               ORDER BY possible_savings DESC
    """.format(
        min_delta=MIN_GHOST_GENERIC_DELTA,
        extra_conditions=extra_conditions
    )
    if group_by == 'presentation':
        grouping = """
          SELECT
            date, pct, bnf_code,
            MAX(median_ppu) AS median_ppu,
            MAX(price_per_unit) AS price_per_unit,
            SUM(quantity) AS quantity,
            MAX(product_name) AS product_name,
            SUM(possible_savings) AS possible_savings
          FROM ({}) s
          GROUP BY date, pct, bnf_code"""
        sql = grouping.format(sql)
    elif group_by == 'all':
        grouping = """
          SELECT
            SUM(possible_savings) AS possible_savings
          FROM ({}) s"""
        sql = grouping.format(sql)

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        results = utils.dictfetchall(cursor)
    response = Response(results)
    if request.accepted_renderer.format == 'csv':
        filename = "%s.csv" % (filename)
        response['content-disposition'] = "attachment; filename=%s" % filename
    return response


def _aggregate_ppu_sql(original_sql, entity_type):
    """
    Takes a PPU SQL query and modifies it to return savings aggregated over all
    the entities (CCGs or practices) in the original query
    """
    entity_name = "'NHS England'"

    return """
        WITH cte AS ({original_sql})
        SELECT
          -- Fields we're grouping by
          date,
          presentation,

          -- Fields we aggregate over
          SUM(quantity) AS quantity,
          SUM(price_per_unit * quantity) / SUM(quantity) AS price_per_unit,
          SUM(possible_savings) AS possible_savings,

          -- Fixed value fields
          NULL AS pct,
          {pct_name} as pct_name,
          NULL AS practice,
          {practice_name} AS practice_name,

          -- These fields relate to the presentation and so they ought to
          -- have a fixed value throughout the group. However Postgres
          -- doesn't know this, so we need to tell it how to aggregate
          -- these fields. In most cases we just use the modal value.
          MAX(lowest_decile) AS lowest_decile,
          MODE() WITHIN GROUP (ORDER BY formulation_swap)
            AS formulation_swap,
          MODE() WITHIN GROUP (ORDER BY flag_bioequivalence)
            AS flag_bioequivalence,
          MODE() WITHIN GROUP (ORDER BY price_concession)
            AS price_concession,
          MODE() WITHIN GROUP (ORDER BY name) AS name
        FROM cte
        GROUP BY date, presentation
        """.format(
            original_sql=original_sql,
            pct_name=entity_name if entity_type == 'CCG' else 'NULL',
            practice_name="NULL" if entity_type == 'CCG' else entity_name)


@api_view(['GET'])
def total_spending(request, format=None):
    codes = utils.param_to_list(request.query_params.get('code', []))
    codes = utils.get_bnf_codes_from_number_str(codes)
    data = _get_total_prescribing_entries(codes)
    return Response(list(data))


def _get_total_prescribing_entries(bnf_code_prefixes):
    db = get_db()
    items_matrix, quantity_matrix, actual_cost_matrix = _get_prescribing_for_codes(
        db, bnf_code_prefixes
    )
    # If no data at all was found, return early which results in an empty
    # iterator
    if items_matrix is None:
        return
    # This will sum over every practice (whether setting 4 or not) which might
    # not seem like what we want but is what the original API did (it was
    # powered by the `vw__presentation_summary` table which summed over all
    # practice types)
    grouper = group_by('all_practices')
    items_matrix = grouper(items_matrix)
    quantity_matrix = grouper(quantity_matrix)
    actual_cost_matrix = grouper(actual_cost_matrix)
    # Yield entries for each date (unlike _get_prescribing_entries below we
    # return a value for each date even if it's zero as this is what the
    # original API did)
    for date, col_offset in sorted(db.date_offsets.items()):
        index = (0, col_offset)
        yield {
            'items': items_matrix[index],
            'quantity': quantity_matrix[index],
            'actual_cost': round(actual_cost_matrix[index], 2),
            'date': date,
        }


@api_view(['GET'])
def tariff(request, format=None):
    # This view uses raw SQL as we cannot produce the LEFT OUTER JOIN using the
    # ORM.
    codes = utils.param_to_list(request.query_params.get('codes', []))

    query = '''
    SELECT dmd_tariffprice.date AS date,
           dmd_tariffprice.price_pence AS price_pence,
           dmd_vmpp.nm AS vmpp,
           dmd_vmpp.vppid AS vmpp_id,
           dmd_product.bnf_code AS product,
           dmd_ncsoconcession.price_concession_pence AS concession,
           dmd_lookup_dt_payment_category.desc AS tariff_category,
           dmd_vmpp.qtyval AS pack_size
    FROM dmd_tariffprice
        INNER JOIN dmd_lookup_dt_payment_category
            ON dmd_tariffprice.tariff_category_id = dmd_lookup_dt_payment_category.cd
        INNER JOIN dmd_product
            ON dmd_tariffprice.product_id = dmd_product.dmdid
        INNER JOIN dmd_vmpp
            ON dmd_tariffprice.vmpp_id = dmd_vmpp.vppid
        LEFT OUTER JOIN dmd_ncsoconcession
            ON (dmd_tariffprice.date = dmd_ncsoconcession.date
                AND dmd_tariffprice.vmpp_id = dmd_ncsoconcession.vmpp_id)
    '''

    if codes:
        query += ' WHERE dmd_product.bnf_code IN ('
        query += ','.join('%s' for _ in range(len(codes)))
        query += ')'
        params = [codes]
    else:
        params = None

    query += ' ORDER BY date'

    data = utils.execute_query(query, params)
    response = Response(data)
    if request.accepted_renderer.format == 'csv':
        filename = "tariff.csv"
        response['content-disposition'] = "attachment; filename=%s" % filename
    return response


@api_view(['GET'])
def spending_by_ccg(request, format=None):
    codes = utils.param_to_list(request.query_params.get('code', []))
    codes = utils.get_bnf_codes_from_number_str(codes)
    pct_ids = utils.param_to_list(request.query_params.get('org', []))
    ccgs = PCT.objects.filter(org_type='CCG').order_by('code').only('code', 'name')
    if pct_ids:
        ccgs = ccgs.filter(code__in=pct_ids)
    data = _get_prescribing_entries(codes, ccgs, 'ccg')
    return Response(list(data))


@api_view(['GET'])
def spending_by_practice(request, format=None):
    codes = utils.param_to_list(request.query_params.get('code', []))
    codes = utils.get_bnf_codes_from_number_str(codes)
    org_ids = utils.param_to_list(request.query_params.get('org', []))
    date = request.query_params.get('date', None)

    if not date and not org_ids:
        err = 'Error: You must supply either '
        err += 'a list of practice IDs or a date parameter, e.g. '
        err += 'date=2015-04-01'
        return Response(err, status=400)

    practice_ids = utils.get_practice_ids_from_org(org_ids)
    practices = Practice.objects.order_by('code')
    if practice_ids:
        practices = practices.filter(code__in=practice_ids)
    data = _get_prescribing_entries(codes, practices, 'practice', date=date)
    return Response(list(data))


def _get_prescribing_entries(bnf_code_prefixes, orgs, org_type, date=None):
    db = get_db()
    items_matrix, quantity_matrix, actual_cost_matrix = _get_prescribing_for_codes(
        db, bnf_code_prefixes
    )
    # If no data at all was found, return early which results in an empty
    # iterator
    if items_matrix is None:
        return
    # Group together practice level data to the appropriate organisation level
    grouper = group_by(org_type)
    items_matrix = grouper(items_matrix)
    quantity_matrix = grouper(quantity_matrix)
    actual_cost_matrix = grouper(actual_cost_matrix)
    # `grouper.offsets` maps each organisation's primary key to its row offset
    # within the matrices. We pair each organisation with its row offset,
    # ignoring those organisations which aren't in the mapping (which implies
    # that they did not prescribe in this period)
    org_offsets = [
        (org, grouper.offsets[org.pk])
        for org in orgs
        if org.pk in grouper.offsets
    ]
    # Pair each date with its column offset (either all available dates or just
    # the specified one)
    if date:
        date_offsets = [(date, db.date_offsets[date])]
    else:
        date_offsets = sorted(db.date_offsets.items())
    # Yield entries for each organisation on each date
    for date, col_offset in date_offsets:
        for org, row_offset in org_offsets:
            index = (row_offset, col_offset)
            items = items_matrix[index]
            # Mimicking the behaviour of the existing API, we don't return
            # entries where there was no prescribing
            if items == 0:
                continue
            entry = {
                'items': items,
                'quantity': quantity_matrix[index],
                'actual_cost': round(actual_cost_matrix[index], 2),
                'date': date,
                'row_id': org.pk,
                'row_name': org.name,
            }
            # Practices get some extra attributes in the existing API
            if org_type == 'practice':
                entry['ccg'] = org.ccg_id
                entry['setting'] = org.setting
            yield entry


def _get_prescribing_for_codes(db, bnf_code_prefixes):
    if bnf_code_prefixes:
        where_clause = ' OR '.join(['bnf_code LIKE ?'] * len(bnf_code_prefixes))
        params = [code + '%' for code in bnf_code_prefixes]
    else:
        where_clause = '1=1'
        params = []
    sql = (
        """
        SELECT
            matrix_sum(items) AS items,
            matrix_sum(quantity) AS quantity,
            matrix_sum(actual_cost) AS actual_cost
        FROM
            presentation
        WHERE
            items IS NOT NULL AND ({})
        """.format(
            where_clause
        )
    )
    items, quantity, actual_cost = db.query_one(sql, params)
    # Convert from pence to pounds
    if actual_cost is not None:
        actual_cost = actual_cost / 100.0
    return items, quantity, actual_cost


def _get_query_for_total_spending(codes):
    # The CTE at the start ensures we return rows for every month in
    # the last five years, even if that's zeros
    query = """
    WITH all_dates AS (
        SELECT
            MAX(current_at)::date - (d.date||'month')::interval AS date
        FROM
            generate_series(0, 59) AS d(date),
            frontend_importlog
        WHERE
            category = 'prescribing'
        GROUP BY
            category,
            d.date
        ORDER BY
            date
    )
    SELECT
        COALESCE(SUM(cost), 0) AS actual_cost,
        COALESCE(SUM(items), 0) AS items,
        COALESCE(SUM(quantity), 0) AS quantity,
        all_dates.date::date AS date
    FROM (
        SELECT *
        FROM
        vw__presentation_summary
        WHERE %s
    ) pr
    RIGHT OUTER JOIN all_dates
    ON all_dates.date = pr.processing_date
    GROUP BY date
    ORDER BY date;"""

    if codes:
        code_clauses = ['presentation_code LIKE %s'] * len(codes)
    else:
        code_clauses = None

    where_condition = _build_where_condition([code_clauses])

    return query % where_condition


def _get_query_for_chemicals_or_sections_by_ccg(codes, pct_ids, spending_type):
    query = '''
    SELECT pc.code as row_id,
        pc.name as row_name,
        pr.processing_date as date,
        SUM(pr.cost) AS actual_cost,
        SUM(pr.items) AS items,
        SUM(pr.quantity) AS quantity
    FROM vw__chemical_summary_by_ccg pr
    JOIN frontend_pct pc ON pr.pct_id=pc.code
    AND pc.org_type='CCG'
    WHERE %s
    GROUP BY pc.code, pc.name, date
    ORDER BY date, pc.code
    '''

    if spending_type == BnfHierarchy.section:
        chemical_clauses = ['pr.chemical_id LIKE %s'] * len(codes)
    elif spending_type == BnfHierarchy.chemical:
        chemical_clauses = ['pr.chemical_id = %s'] * len(codes)
    else:
        chemical_clauses = None

    if pct_ids:
        pct_clauses = ['pr.pct_id = %s'] * len(pct_ids)
    else:
        pct_clauses = None

    where_condition = _build_where_condition([
        chemical_clauses,
        pct_clauses,
    ])

    return query % where_condition


def _get_query_for_presentations_by_ccg(codes, pct_ids):
    query = '''
    SELECT
        pc.code as row_id,
        pc.name as row_name,
        pr.processing_date as date,
        SUM(pr.items) AS items,
        SUM(pr.cost) AS actual_cost,
        SUM(pr.quantity) AS quantity
    FROM vw__presentation_summary_by_ccg pr
    JOIN frontend_pct pc ON pr.pct_id=pc.code
    AND pc.org_type='CCG'
    WHERE %s
    GROUP BY pc.code, pc.name, date
    ORDER BY date, pc.code
    '''

    code_clauses = ['pr.presentation_code LIKE %s'] * len(codes)

    if pct_ids:
        pct_clauses = ['pr.pct_id = %s'] * len(pct_ids)
    else:
        pct_clauses = None

    where_condition = _build_where_condition([
        code_clauses,
        pct_clauses,
    ])

    return query % where_condition


def _get_total_spending_by_practice(practice_ids, date):
    query = '''
    SELECT
        pr.practice_id AS row_id,
        pc.name AS row_name,
        pc.setting AS setting,
        pc.ccg_id AS ccg,
        pr.processing_date AS date,
        pr.cost AS actual_cost,
        pr.items AS items,
        pr.quantity AS quantity
    FROM vw__practice_summary pr
    JOIN frontend_practice pc ON pr.practice_id=pc.code
    WHERE %s
    ORDER BY date, pr.practice_id
    '''

    if practice_ids:
        practice_clauses = ['pr.practice_id = %s'] * len(practice_ids)
    else:
        practice_clauses = None

    if date:
        date_clause = 'pr.processing_date = %s'
    else:
        date_clause = None

    where_condition = _build_where_condition([
        practice_clauses,
        date_clause,
    ])

    return query % where_condition


def _get_chemicals_or_sections_by_practice(codes, practice_ids, spending_type,
                                           date):
    query = '''
    SELECT
        pc.code AS row_id,
        pc.name AS row_name,
        pc.setting AS setting,
        pc.ccg_id AS ccg,
        pr.processing_date AS date,
        SUM(pr.cost) AS actual_cost,
        SUM(pr.items) AS items,
        SUM(pr.quantity) AS quantity
    FROM vw__chemical_summary_by_practice pr
    JOIN frontend_practice pc ON pr.practice_id=pc.code
    WHERE %s
    GROUP BY pc.code, pc.name, date
    ORDER BY date, pc.code
    '''

    if spending_type == BnfHierarchy.section:
        chemical_clauses = ['pr.chemical_id LIKE %s'] * len(codes)
    elif spending_type == BnfHierarchy.chemical:
        chemical_clauses = ['pr.chemical_id = %s'] * len(codes)
    else:
        assert False

    if practice_ids:
        practice_clauses = ['pr.practice_id = %s'] * len(practice_ids)
    else:
        practice_clauses = None

    if date:
        date_clause = 'pr.processing_date = %s'
    else:
        date_clause = None

    where_condition = _build_where_condition([
        chemical_clauses,
        practice_clauses,
        date_clause,
    ])

    return query % where_condition


def _get_presentations_by_practice(codes, org_ids, date):
    query = '''
    SELECT
        pc.code AS row_id,
        pc.name AS row_name,
        pc.setting AS setting,
        pc.ccg_id AS ccg,
        pr.processing_date AS date,
        SUM(pr.actual_cost) AS actual_cost,
        SUM(pr.total_items) AS items,
        CAST(SUM(pr.quantity) AS bigint) AS quantity
    FROM frontend_prescription pr
    JOIN frontend_practice pc ON pr.practice_id=pc.code
    WHERE %s
    GROUP BY pc.code, pc.name, date
    ORDER BY date, pc.code
    '''

    code_clauses = ['pr.presentation_code LIKE %s'] * len(codes)

    org_clauses = []
    if org_ids:
        for org_id in org_ids:
            if len(org_id) == 3:
                org_clauses.append('pc.ccg_id = %s')
            else:
                org_clauses.append('pc.code = %s')

    if date:
        date_clause = 'pr.processing_date = %s'
    else:
        date_clause = None

    where_condition = _build_where_condition([
        code_clauses,
        org_clauses,
        date_clause,
    ])

    return query % where_condition


def _build_where_condition(clauses):
    fragments = []

    for clause in clauses:
        if clause is None:
            continue
        elif isinstance(clause, str):
            fragments.append(clause)
        elif isinstance(clause, list):
            if len(clause) == 0:
                continue
            elif len(clause) == 1:
                fragments.append(clause[0])
            else:
                fragment = '(' + ' OR '.join(clause) + ')'
                fragments.append(fragment)
        else:
            assert False, 'Unexpected clause: {}'.format(clause)

    if not fragments:
        return '1 = 1'
    else:
        return ' AND '.join(fragments)
