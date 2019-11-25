from collections import namedtuple

from django.db import connection
from django.db.models import Max

from dateutil.relativedelta import relativedelta
from dateutil.parser import parse as parse_date
import numpy

from frontend.models import NCSOConcession, Presentation
from matrixstore.db import get_db, get_row_grouper


# The tariff (or concession) price is not what actually gets paid as each CCG
# will have some kind of discount with the dispenser. However the average
# discount has been pretty consistent over the years so we use that here.
NATIONAL_AVERAGE_DISCOUNT_PERCENTAGE = 7.2


ConcessionPriceMatrices = namedtuple(
    "ConcessionPriceMatrices",
    "bnf_code_offsets date_offsets tariff_prices price_increases",
)


ConcessionCostMatrices = namedtuple(
    "ConcessionCostMatrices",
    "bnf_code_offsets date_offsets quantities tariff_costs extra_costs",
)


def ncso_spending_for_entity(entity, entity_type, num_months, current_month=None):
    org_type, org_id = _get_org_type_and_id(entity, entity_type)
    end_date = NCSOConcession.objects.aggregate(Max("date"))["date__max"]
    # In practice, we always have at least one NCSOConcession object but we
    # need to handle the empty case in testing
    if not end_date:
        return []
    start_date = end_date - relativedelta(months=num_months - 1)
    last_prescribing_date = parse_date(get_db().dates[-1]).date()
    costs = _get_concession_cost_matrices(start_date, end_date, org_type, org_id)
    # Sum together costs over all presentations (i.e. all rows)
    tariff_costs = numpy.sum(costs.tariff_costs, axis=0)
    extra_costs = numpy.sum(costs.extra_costs, axis=0)
    results = []
    for date_str, offset in sorted(costs.date_offsets.items()):
        date = parse_date(date_str).date()
        if extra_costs[offset] == 0:
            continue
        entry = {
            "month": date,
            "tariff_cost": float(tariff_costs[offset]),
            "additional_cost": float(extra_costs[offset]),
            "is_estimate": date > last_prescribing_date,
            "last_prescribing_date": last_prescribing_date,
        }
        if current_month is not None:
            entry["is_incomplete_month"] = date >= current_month
        results.append(entry)
    return results


def ncso_spending_breakdown_for_entity(entity, entity_type, month):
    org_type, org_id = _get_org_type_and_id(entity, entity_type)
    costs = _get_concession_cost_matrices(month, month, org_type, org_id)
    # As we're only fetching costs for a single month we get matrices with just
    # a single column, which we slice out below. It would be perfectly possible
    # to generate a breakdown for a range of months, in which case we would use
    # `numpy.sum(tariff_costs, axis=1)` to sum across dates. However, if we do
    # this then we also need to alter the `_get_concession_prices` function to
    # fetch tariff costs for all dates in the range, not just those dates on
    # which there is a price concession.
    tariff_costs = costs.tariff_costs[:, 0]
    extra_costs = costs.extra_costs[:, 0]
    quantities = costs.quantities[:, 0]
    names = Presentation.names_for_bnf_codes(list(costs.bnf_code_offsets.keys()))
    results = []
    for bnf_code, offset in costs.bnf_code_offsets.items():
        results.append(
            (
                bnf_code,
                names[bnf_code],
                int(quantities[offset]),
                float(tariff_costs[offset]),
                float(extra_costs[offset]),
            )
        )
    # Sort by "additional cost" column, descending
    results.sort(key=lambda i: i[4], reverse=True)
    return results


def _get_org_type_and_id(entity, entity_type):
    if entity_type == "all_england":
        org_type = "all_practices"
        org_id = None
    else:
        org_type = entity_type if entity_type != "CCG" else "ccg"
        org_id = entity.code
    return org_type, org_id


def _get_concession_cost_matrices(min_date, max_date, org_type, org_id):
    """
    Given a date range (inclusive) and an organisation return a set of matrices
    detailing all spending affected by price concessions during the period.

    Returns a ConcessionCostMatrices object with the following attributes:

        bnf_code_offsets: Maps BNF codes which have a price concession to their
                          row offset in the matrices

            date_offsets: Maps date strings to their column offset in the
                          matrices

              quantities: Matrix giving, for each BNF code and date, the
                          quantity prescribed of that presentation by the
                          specified organisation

            tariff_costs: Matrix giving, for each BNF code and date, the cost
                          of the above prescriptions at standard Drug Tariff
                          prices

             extra_costs: Matrix giving, for each BNF code and date, the cost
                          increase due to price concessions

    """
    prices = _get_concession_price_matrices(min_date, max_date)
    quantities = _get_prescribed_quantity_matrix(
        prices.bnf_code_offsets, prices.date_offsets, org_type, org_id
    )
    return ConcessionCostMatrices(
        bnf_code_offsets=prices.bnf_code_offsets,
        date_offsets=prices.date_offsets,
        quantities=quantities,
        tariff_costs=prices.tariff_prices * quantities,
        extra_costs=prices.price_increases * quantities,
    )


def _get_prescribed_quantity_matrix(bnf_code_offsets, date_offsets, org_type, org_id):
    """
    Given a mapping of BNF codes to row offsets and dates to column offsets,
    return a matrix giving the quantity of those presentations prescribed on
    those dates by the specified organisation (given by its type and ID).

    If the dates extend beyond the latest date for which we have prescribing
    data then we just project the last month forwards (e.g. if we only have
    prescriptions up to March but have price concessions up to May then
    we just assume the same quantities as for March were prescribed in April
    and May).
    """
    db = get_db()
    group_by_org = get_row_grouper(org_type)
    shape = (len(bnf_code_offsets), len(date_offsets))
    quantities = numpy.zeros(shape, dtype=numpy.int_)
    # If this organisation is not in the set of available groups (because it
    # has no prescribing data) then return the zero-valued quantity matrix
    if org_id not in group_by_org.offsets:
        return quantities
    # Find the columns corresponding to the dates we're interested in
    columns_selector = _get_date_columns_selector(db.date_offsets, date_offsets)
    prescribing = _get_quantities_for_bnf_codes(db, list(bnf_code_offsets.keys()))
    for bnf_code, quantity in prescribing:
        # Remap the date columns to just the dates we want
        quantity = quantity[columns_selector]
        # Sum the prescribing for the given organisation
        quantity = group_by_org.sum_one_group(quantity, org_id)
        # Write that sum into the quantities matrix at the correct offset for
        # the current BNF code
        row_offset = bnf_code_offsets[bnf_code]
        quantities[row_offset] = quantity
    return quantities


def _get_date_columns_selector(available_date_offsets, required_date_offsets):
    """
    Return a numpy "fancy index" which maps one set of matrix columns to
    another. Specifically, it will take a matrix with the "available" date
    columns and transform it to one with the "required" columns.

    If any of the required dates are greater than the latest available date
    then the last available date will be used in its place.

    Example:

    >>> available = {'2019-01': 0, '2019-02': 1, '2019-03': 2}
    >>> required  = {'2019-02': 0, '2019-03': 1, '2019-04': 2}

    >>> index = _get_date_columns_selector(available, required)

    >>> matrix = numpy.array([
    ...   [1, 2, 3],
    ...   [4, 5, 6],
    ... ])

    >>> matrix[index]
    array([[2, 3, 3],
           [5, 6, 6]])
    """
    max_available_date = max(available_date_offsets)
    columns = []
    for date in sorted(required_date_offsets):
        if date > max_available_date:
            date = max_available_date
        columns.append(available_date_offsets[date])
    # We want all rows
    rows = slice(None, None, None)
    return rows, columns


def _get_quantities_for_bnf_codes(db, bnf_codes):
    """
    Return the prescribed quantity matrices for the given list of BNF codes
    """
    return db.query(
        """
        SELECT
          bnf_code, quantity
        FROM
          presentation
        WHERE
          bnf_code IN ({})
        """.format(
            ",".join(["?"] * len(bnf_codes))
        ),
        bnf_codes,
    )


def _get_concession_price_matrices(min_date, max_date):
    """
    Return details of NCSO price concessions in the given date range
    (inclusive)

    Returns a ConcessionPriceMatrices object with the following attributes:

        bnf_code_offsets: Maps BNF codes which have a price concession to their
                          row offset in the matrices

            date_offsets: Maps date strings to their column offset in the
                          matrices

           tariff_prices: Matrix giving, for each BNF code and date, the
                          standard Drug Tariff price for that presentation (in
                          pounds-per-unit)

         price_increases: Matrix giving, for each BNF code and date, the price
                          increase due to concessions (in pounds-per-unit)

    """
    # Fetch list of concessions and associated tariff prices from Postgres
    concessions = _get_concession_prices(min_date, max_date)
    # Construct the BNF code and date indices we need to store these prices in
    # matrix form
    date_offsets = {
        str(date): i for (i, date) in enumerate(_get_dates_in_range(min_date, max_date))
    }
    bnf_codes = {concession[1] for concession in concessions}
    bnf_code_offsets = {bnf_code: i for (i, bnf_code) in enumerate(bnf_codes)}
    # Construct the matrices we need
    shape = (len(bnf_code_offsets), len(date_offsets))
    tariff_prices = numpy.zeros(shape, dtype=numpy.float_)
    price_increases = numpy.zeros(shape, dtype=numpy.float_)
    # Loop over the concessions and write them into the matrices
    for date, bnf_code, tariff_price, price_increase, quantity_per_pack in concessions:
        index = (bnf_code_offsets[bnf_code], date_offsets[str(date)])
        # Convert prices from per-pack into per-unit
        tariff_price = tariff_price / quantity_per_pack
        price_increase = price_increase / quantity_per_pack
        # Price concessions are defined at the product-pack level but we only
        # have prescribing data at product level. Occasionally there are
        # multiple simultaneous concessions for a given product with different
        # implied prices-per-unit for different pack sizes. As we can't know
        # from our data which pack size was dispensed we just use the highest
        # per-unit price.
        if price_increase > price_increases[index]:
            price_increases[index] = price_increase
            tariff_prices[index] = tariff_price
    # Apply the national average discount to get a better approximation of the
    # actual price paid, and while we're at it convert from pence to pounds to
    # make later calcuations easier
    discount_factor = (100 - NATIONAL_AVERAGE_DISCOUNT_PERCENTAGE) / (100 * 100)
    tariff_prices *= discount_factor
    price_increases *= discount_factor
    return ConcessionPriceMatrices(
        bnf_code_offsets=bnf_code_offsets,
        date_offsets=date_offsets,
        tariff_prices=tariff_prices,
        price_increases=price_increases,
    )


def _get_dates_in_range(date_start, date_end):
    date = date_start
    while date <= date_end:
        yield date
        date = date + relativedelta(months=1)


def _get_concession_prices(min_date, max_date):
    """
    Gets all NCSO price concessions in the given period (where both min and max
    are inclusive), returning an iterable of tuples of the form:

                     date: Datetime instance giving the month of the concession

                 bnf_code: Presentation to which concession is applied

             tariff_price: Standard drug tariff price in pence-per-pack

           price_increase: The *extra* cost of the price concession (i.e. the
                           cost above the tariff price) in pence-per-pack

        quantity_per_pack: Divide prescribed quantity by this to get number of
                           packs

    Note that because concessions are defined at the product-pack level and BNF
    codes refer to products it's possible to have multiple different concession
    prices for the same (BNF code, date) pair.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              ncso.date AS date,
              vmpp.bnf_code AS bnf_code,
              tariff.price_pence AS tariff_price,
              COALESCE(ncso.price_pence - tariff.price_pence, 0) AS price_increase,
              CASE WHEN presentation.quantity_means_pack THEN
                  1
                ELSE
                  vmpp.qtyval
                END
              AS quantity_per_pack
            FROM
              frontend_ncsoconcession AS ncso
            JOIN
              frontend_tariffprice AS tariff
            ON
              ncso.vmpp_id = tariff.vmpp_id AND ncso.date = tariff.date
            JOIN
              dmd_vmpp AS vmpp
            ON
              vmpp.vppid=ncso.vmpp_id
            JOIN
              frontend_presentation AS presentation
            ON
              presentation.bnf_code = vmpp.bnf_code
            WHERE
              ncso.date >= %(min_date)s AND ncso.date <= %(max_date)s
            """,
            {"min_date": min_date, "max_date": max_date},
        )
        return cursor.fetchall()
