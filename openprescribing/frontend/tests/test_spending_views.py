import collections

from django.test import TestCase
from django.db.models import Max

from dateutil.relativedelta import relativedelta
from dateutil.parser import parse as parse_date

from frontend.models import Prescription, Presentation, NCSOConcessionBookmark
from frontend.models import NCSOConcession, TariffPrice
from frontend.views.spending_utils import (
    NATIONAL_AVERAGE_DISCOUNT_PERCENTAGE,
    ncso_spending_for_entity,
    ncso_spending_breakdown_for_entity,
)
from frontend.tests.data_factory import DataFactory
from matrixstore.tests.decorators import copy_fixtures_to_matrixstore


@copy_fixtures_to_matrixstore
class TestSpendingViews(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestSpendingViews, cls).setUpClass()
        factory = DataFactory()
        cls.months = factory.create_months_array(start_date="2018-02-01", num_months=6)
        # Our NCSO and tariff data extends further than our prescribing data by
        # a couple of months
        cls.prescribing_months = cls.months[:-2]
        # Create some high level orgs
        cls.regional_team = factory.create_regional_team()
        cls.stp = factory.create_stp()
        # Create some CCGs (we need more than one so we can test aggregation
        # across CCGs at the All England level)
        cls.ccgs = [
            factory.create_ccg(stp=cls.stp, regional_team=cls.regional_team)
            for _ in range(2)
        ]
        # Create a PCN (one will do)
        cls.pcn = factory.create_pcn()
        # Populate those CCGs with practices
        cls.practices = []
        for ccg in cls.ccgs:
            for _ in range(2):
                cls.practices.append(factory.create_practice(ccg=ccg, pcn=cls.pcn))
        # Create some presentations
        cls.presentations = factory.create_presentations(6, vmpp_per_presentation=2)
        # Create drug tariff and price concessions costs for these presentations
        factory.create_tariff_and_ncso_costings_for_presentations(
            cls.presentations, months=cls.months
        )
        # Create prescribing for each of the practices we've created
        for practice in cls.practices:
            factory.create_prescribing_for_practice(
                practice, presentations=cls.presentations, months=cls.prescribing_months
            )
        # Pull out an individual practice and CCG to use in our tests
        cls.practice = cls.practices[0]
        cls.ccg = cls.ccgs[0]

    def test_ncso_spending_methods(self):
        entities = [
            (self.practice, "practice"),
            (self.ccg, "CCG"),
            (None, "all_england"),
        ]
        for entity, entity_type in entities:
            # When we switch to Python 3 we should use the subTest method to
            # make test failures clearer:
            # https://docs.python.org/3/library/unittest.html#subtests
            # with self.subTest(entity=entity, entity_type=entity_type):
            self.validate_ncso_spending_for_entity(
                entity,
                entity_type,
                len(self.months),
                current_month=parse_date(self.months[-1]).date(),
            )
            self.validate_ncso_spending_breakdown_for_entity(
                entity, entity_type, parse_date(self.months[0]).date()
            )
            self.validate_ncso_spending_breakdown_for_entity(
                entity, entity_type, parse_date(self.months[-1]).date()
            )

    def validate_ncso_spending_for_entity(self, *args, **kwargs):
        # with self.subTest(function='_ncso_spending_for_entity'):
        results = ncso_spending_for_entity(*args, **kwargs)
        expected = recalculate_ncso_spending_for_entity(*args, **kwargs)
        self.assertEqual(round_floats(results), round_floats(expected))

    def validate_ncso_spending_breakdown_for_entity(self, *args, **kwargs):
        # with self.subTest(function='_ncso_spending_breakdown_for_entity'):
        results = ncso_spending_breakdown_for_entity(*args, **kwargs)
        expected = recalculate_ncso_spending_breakdown_for_entity(*args, **kwargs)
        self.assertEqual(round_floats(results), round_floats(expected))

    def test_spending_views(self):
        # Basic smoketest which just checks that the view loads OK and has
        # something we expect in it
        urls = [
            "/practice/{}/concessions/".format(self.practice.code),
            "/pcn/{}/concessions/".format(self.pcn.code),
            "/ccg/{}/concessions/".format(self.ccg.code),
            "/stp/{}/concessions/".format(self.stp.code),
            "/regional-team/{}/concessions/".format(self.regional_team.code),
            "/all-england/concessions/",
        ]
        for url in urls:
            # with self.subTest(url=url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            ctx = response.context
            self.assertEqual(
                ctx["breakdown_date"].strftime("%Y-%m-%d"), self.months[-1]
            )

    def test_alert_signup(self):
        factory = DataFactory()
        factory.create_user(email="alice@example.com")
        factory.create_ncso_concessions_bookmark(None)

        self.assertEqual(NCSOConcessionBookmark.objects.count(), 1)

        url = "/practice/{}/concessions/".format(self.practice.code)
        data = {
            "email": "alice@example.com",
            "practice": self.practice.code,
            "newsletters": ["alerts"],
        }
        response = self.client.post(url, data, follow=True)
        self.assertContains(
            response, "Check your email and click the confirmation link"
        )

        self.assertEqual(NCSOConcessionBookmark.objects.count(), 2)
        bookmark = NCSOConcessionBookmark.objects.last()
        self.assertEqual(bookmark.practice, self.practice)
        self.assertEqual(bookmark.user.email, "alice@example.com")
        self.assertEqual(bookmark.approved, True)

    def test_all_england_alert_signup(self):
        factory = DataFactory()
        factory.create_user(email="alice@example.com")
        factory.create_ncso_concessions_bookmark(self.practice)

        self.assertEqual(NCSOConcessionBookmark.objects.count(), 1)

        url = "/all-england/concessions/"
        data = {"email": "alice@example.com", "newsletters": ["alerts"]}
        response = self.client.post(url, data, follow=True)
        self.assertContains(
            response, "Check your email and click the confirmation link"
        )

        self.assertEqual(NCSOConcessionBookmark.objects.count(), 2)
        bookmark = NCSOConcessionBookmark.objects.order_by("id").last()
        self.assertEqual(bookmark.practice, None)
        self.assertEqual(bookmark.pct, None)
        self.assertEqual(bookmark.user.email, "alice@example.com")
        self.assertEqual(bookmark.approved, True)

    def test_alert_signup_form(self):
        factory = DataFactory()
        user = factory.create_user()
        url = "/practice/{}/concessions/".format(self.practice.code)

        # Check form is displayed when user not loged in.
        response = self.client.get(url)
        self.assertContains(response, "Get email updates")

        # Now log user in.
        self.client.force_login(user)

        # Check form is displayed when user has no bookmarks.
        response = self.client.get(url)
        self.assertContains(response, "Get email updates")

        # Create bookmarks for CCG and All England, and check that form is
        # still displayed.
        factory.create_ncso_concessions_bookmark(self.ccg, user)
        factory.create_ncso_concessions_bookmark(None, user)
        response = self.client.get(url)
        self.assertContains(response, "Get email updates")

        # Create bookmark for practice, and check that form is not displayed.
        factory.create_ncso_concessions_bookmark(self.practice, user)
        response = self.client.get(url)
        self.assertNotContains(response, "Get email updates")
        self.assertContains(response, "already signed up")

    def test_all_england_alert_signup_form(self):
        factory = DataFactory()
        user = factory.create_user()
        url = "/all-england/concessions/".format(self.practice.code)

        # Check form is displayed when user not loged in.
        response = self.client.get(url)
        self.assertContains(response, "Get email updates")

        # Now log user in.
        self.client.force_login(user)

        # Check form is displayed when user has no bookmarks.
        response = self.client.get(url)
        self.assertContains(response, "Get email updates")

        # Create bookmarks for practice and CCG, and check that form is still
        # displayed.
        factory.create_ncso_concessions_bookmark(self.practice, user)
        factory.create_ncso_concessions_bookmark(self.ccg, user)
        response = self.client.get(url)
        self.assertContains(response, "Get email updates")

        # Create bookmark for All England, and check that form is not displayed.
        factory.create_ncso_concessions_bookmark(None, user)
        response = self.client.get(url)
        self.assertNotContains(response, "Get email updates")
        self.assertContains(response, "already signed up")


def round_floats(value):
    if isinstance(value, float):
        return round(value, 5)
    elif isinstance(value, list):
        return [round_floats(i) for i in value]
    elif isinstance(value, tuple):
        return tuple(round_floats(i) for i in value)
    elif isinstance(value, dict):
        return {k: round_floats(v) for (k, v) in value.items()}
    else:
        return value


##############################################################################
# Below are functions which reimplement the NCSO spending calculations using
# (as far as possible) Python rather than SQL so we have something to test the
# SQL against
##############################################################################


def recalculate_ncso_spending_for_entity(
    entity, entity_type, num_months, current_month=None
):
    prescriptions = get_prescriptions_for_entity(entity, entity_type)
    last_prescribing_date = get_last_prescribing_date()
    quantities = aggregate_quantities_by_date_and_bnf_code(prescriptions)
    concessions = get_ncso_concessions(*get_start_and_end_dates(num_months))
    concessions = add_quantities_to_concessions(
        concessions, quantities, last_prescribing_date
    )
    concessions = filter_zero_prescribing_quantities(concessions)
    concessions = calculate_costs_for_concessions(concessions)
    concessions = filter_duplicate_concessions(concessions)
    results = []
    for row in aggregate_by_date(concessions):
        result = {
            "month": row["date"],
            "tariff_cost": row["tariff_cost"],
            "additional_cost": row["additional_cost"],
            "is_estimate": row["is_estimate"],
            "last_prescribing_date": last_prescribing_date,
        }
        if current_month is not None:
            result["is_incomplete_month"] = result["month"] >= current_month
        results.append(result)
    results.sort(key=lambda row: row["month"])
    return results


def recalculate_ncso_spending_breakdown_for_entity(entity, entity_type, month):
    prescriptions = get_prescriptions_for_entity(entity, entity_type)
    last_prescribing_date = get_last_prescribing_date()
    quantities = aggregate_quantities_by_date_and_bnf_code(prescriptions)
    concessions = get_ncso_concessions(month, month)
    concessions = add_quantities_to_concessions(
        concessions, quantities, last_prescribing_date
    )
    concessions = filter_zero_prescribing_quantities(concessions)
    concessions = calculate_costs_for_concessions(concessions)
    concessions = filter_duplicate_concessions(concessions)
    results = []
    for row in concessions:
        results.append(
            (
                row["bnf_code"],
                row["product_name"],
                row["quantity"],
                row["tariff_cost"],
                row["additional_cost"],
            )
        )
    results.sort(key=lambda row: (row[4], row[3]), reverse=True)
    return results


def get_prescriptions_for_entity(entity, entity_type):
    query = Prescription.objects.all()
    if entity_type == "practice":
        return query.filter(practice=entity)
    elif entity_type == "CCG":
        return query.filter(pct=entity)
    elif entity_type == "all_england":
        return query
    else:
        raise ValueError("Unknown entity_type: {}".format(entity_type))


def get_start_and_end_dates(num_months):
    end_date = NCSOConcession.objects.aggregate(Max("date"))["date__max"]
    start_date = end_date - relativedelta(months=(num_months - 1))
    return start_date, end_date


def get_ncso_concessions(start_date, end_date):
    concessions = []
    query = NCSOConcession.objects.filter(date__gte=start_date, date__lte=end_date)
    for ncso in query:
        vmpp = ncso.vmpp
        tariff = TariffPrice.objects.get(vmpp=vmpp, date=ncso.date)
        presentation = Presentation.objects.get(bnf_code=vmpp.bnf_code)
        concessions.append(
            {
                "date": ncso.date,
                "bnf_code": vmpp.bnf_code,
                "product_name": vmpp.vmp.nm,
                "tariff_price_pence": tariff.price_pence,
                "concession_price_pence": ncso.price_pence,
                "quantity_value": float(ncso.vmpp.qtyval),
                "quantity_means_pack": presentation.quantity_means_pack,
            }
        )
    return concessions


def aggregate_quantities_by_date_and_bnf_code(prescriptions):
    quantities = collections.defaultdict(float)
    for prescription in prescriptions:
        key = (prescription.processing_date, prescription.presentation_code)
        quantities[key] += prescription.quantity
    return quantities


def get_last_prescribing_date():
    result = Prescription.objects.aggregate(Max("processing_date"))
    return result["processing_date__max"]


def add_quantities_to_concessions(concessions, quantities, last_prescribing_date):
    for concession in concessions:
        source_date = concession["date"]
        is_estimate = False
        if source_date > last_prescribing_date:
            source_date = last_prescribing_date
            is_estimate = True
        key = (source_date, concession["bnf_code"])
        concession["quantity"] = quantities[key]
        concession["is_estimate"] = is_estimate
    return concessions


def filter_duplicate_concessions(concessions):
    """
    Because concessions are made at the product-pack level but we only have
    prescribing data at the product level, we sometimes end up with multiple
    concessions matching to a single product on the same date. In this case we
    use only the highest priced concession.
    """
    costs = []
    for index, concession in enumerate(concessions):
        key = "{}:{}".format(concession["bnf_code"], concession["date"])
        costs.append((key, concession["additional_cost"], index))
    selected = {key: index for (key, cost, index) in sorted(costs)}
    selected = set(selected.values())
    return [
        concession
        for (index, concession) in enumerate(concessions)
        if index in selected
    ]


def filter_zero_prescribing_quantities(concessions):
    return [i for i in concessions if i["quantity"] != 0]


def calculate_costs_for_concessions(concessions):
    for concession in concessions:
        concession.update(calculate_concession_costs(concession))
    return concessions


def calculate_concession_costs(concession):
    if concession["quantity_means_pack"]:
        num_units = concession["quantity"]
    else:
        num_units = concession["quantity"] / concession["quantity_value"]
    tariff_cost_pence = num_units * concession["tariff_price_pence"]
    concession_cost_pence = num_units * concession["concession_price_pence"]
    tariff_cost = tariff_cost_pence / 100
    concession_cost = concession_cost_pence / 100
    tariff_cost_discounted = tariff_cost * (
        1 - (NATIONAL_AVERAGE_DISCOUNT_PERCENTAGE / 100)
    )
    concession_cost_discounted = concession_cost * (
        1 - (NATIONAL_AVERAGE_DISCOUNT_PERCENTAGE / 100)
    )
    return {
        "tariff_cost": tariff_cost_discounted,
        "additional_cost": concession_cost_discounted - tariff_cost_discounted,
    }


def aggregate_by_date(concessions):
    by_date = {}
    for concession in concessions:
        if concession["date"] not in by_date:
            aggregate = {
                "date": concession["date"],
                "is_estimate": concession["is_estimate"],
                "quantity": 0,
                "tariff_cost": 0,
                "additional_cost": 0,
            }
            by_date[concession["date"]] = aggregate
        else:
            aggregate = by_date[concession["date"]]
        aggregate["quantity"] += concession["quantity"]
        aggregate["tariff_cost"] += concession["tariff_cost"]
        aggregate["additional_cost"] += concession["additional_cost"]
    return by_date.values()
