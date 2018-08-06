import csv
import datetime
import json

from django.db import connection

from .api_test_base import ApiTestBase

from frontend.models import ImportLog


def _create_prescribing_tables():
    current = datetime.date(2013, 4, 1)
    cmd = ("DROP TABLE IF EXISTS %s; "
           "CREATE TABLE %s () INHERITS (frontend_prescription)")
    with connection.cursor() as cursor:
        for _ in range(0, 59):
            table_name = "frontend_prescription_%s%s" % (
                current.year, str(current.month).zfill(2))
            cursor.execute(cmd % (table_name, table_name))
            current = datetime.date(
                current.year + (current.month / 12),
                ((current.month % 12) + 1),
                1)
    ImportLog.objects.create(
        current_at=current, category='prescribing')


class TestAPISpendingViewsTariff(ApiTestBase):
    def test_tariff_hit(self):
        url = '/tariff?format=csv&codes=ABCD'
        rows = self._rows_from_api(url)
        self.assertEqual(rows, [
            {'date': '2010-03-01',
             'concession': '',
             'product': 'ABCD',
             'price_pence': '900',
             'tariff_category': 'Part VIIIA Category A',
             'vmpp': 'Bar tablets 84 tablet',
             'pack_size': '84.0'}
        ])

    def test_tariff_hits(self):
        url = '/tariff?format=csv&codes=ABCD,EFGH'
        rows = self._rows_from_api(url)
        self.assertItemsEqual(rows, [
            {'date': '2010-03-01',
             'concession': '',
             'product': 'ABCD',
             'price_pence': '900',
             'tariff_category': 'Part VIIIA Category A',
             'vmpp': 'Bar tablets 84 tablet',
             'pack_size': '84.0'},
            {'date': '2010-03-01',
             'concession': '',
             'product': 'EFGH',
             'price_pence': '2400',
             'tariff_category': 'Part VIIIA Category A',
             'vmpp': 'Foo tablets 84 tablet',
             'pack_size': '84.0'},
            {'date': '2010-04-01',
             'concession': '',
             'product': 'EFGH',
             'price_pence': '1100',
             'tariff_category': 'Part VIIIA Category A',
             'vmpp': 'Foo tablets 84 tablet',
             'pack_size': '84.0'},
        ])

    def test_tariff_miss(self):
        url = '/tariff?format=csv&codes=ABCDE'
        rows = self._rows_from_api(url)
        self.assertEqual(rows, [])

    def test_tariff_all(self):
        url = '/tariff?format=csv'
        rows = self._rows_from_api(url)
        self.assertEqual(len(rows), 3)


class TestSpending(ApiTestBase):
    def _get(self, params):
        params['format'] = 'csv'
        url = '/api/1.0/spending/'
        return self.client.get(url, params)

    def _get_rows(self, params):
        rsp = self._get(params)
        return list(csv.DictReader(rsp.content.splitlines()))

    def test_codes_are_rejected_if_not_same_length(self):
        params = {
            'code': '0202010B0,0202010B0AAAAAA',
        }
        response = self._get(params)
        self.assertEqual(response.status_code, 400)

    def test_404_returned_for_unknown_short_code(self):
        params = {
            'code': '0',
        }
        response = self._get(params)
        self.assertEqual(response.status_code, 404)

    def test_404_returned_for_unknown_dotted_code(self):
        params = {
            'code': '123.456',
        }
        response = self._get(params)
        self.assertEqual(response.status_code, 404)

    def test_total_spending(self):
        _create_prescribing_tables()
        rows = self._get_rows({})

        self.assertEqual(len(rows), 60)
        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '4.61')
        self.assertEqual(rows[0]['items'], '3')
        self.assertEqual(rows[0]['quantity'], '82')
        self.assertEqual(rows[1]['date'], '2013-05-01')
        self.assertEqual(rows[1]['actual_cost'], '0.0')
        self.assertEqual(rows[1]['items'], '0')
        self.assertEqual(rows[1]['quantity'], '0')
        self.assertEqual(rows[19]['date'], '2014-11-01')
        self.assertEqual(rows[19]['actual_cost'], '90.54')
        self.assertEqual(rows[19]['items'], '95')
        self.assertEqual(rows[19]['quantity'], '5142')

    def test_total_spending_by_bnf_section(self):
        _create_prescribing_tables()
        rows = self._get_rows({
            'code': '2'
        })

        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '4.61')
        self.assertEqual(rows[0]['items'], '3')
        self.assertEqual(rows[0]['quantity'], '82')
        self.assertEqual(rows[19]['date'], '2014-11-01')
        self.assertEqual(rows[19]['actual_cost'], '90.54')
        self.assertEqual(rows[19]['items'], '95')
        self.assertEqual(rows[19]['quantity'], '5142')

    def test_total_spending_by_bnf_section_full_code(self):
        _create_prescribing_tables()
        rows = self._get_rows({
            'code': '02',
        })

        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '4.61')
        self.assertEqual(rows[0]['items'], '3')
        self.assertEqual(rows[0]['quantity'], '82')
        self.assertEqual(rows[19]['date'], '2014-11-01')
        self.assertEqual(rows[19]['actual_cost'], '90.54')
        self.assertEqual(rows[19]['items'], '95')
        self.assertEqual(rows[19]['quantity'], '5142')

    def test_total_spending_by_code(self):
        _create_prescribing_tables()
        rows = self._get_rows({
            'code': '0204000I0',
        })

        self.assertEqual(rows[19]['date'], '2014-11-01')
        self.assertEqual(rows[19]['actual_cost'], '36.28')
        self.assertEqual(rows[19]['items'], '33')
        self.assertEqual(rows[19]['quantity'], '2354')

    def test_total_spending_by_codes(self):
        _create_prescribing_tables()
        rows = self._get_rows({
            'code': '0204000I0,0202010B0',
        })

        self.assertEqual(rows[17]['date'], '2014-09-01')
        self.assertEqual(rows[17]['actual_cost'], '36.29')
        self.assertEqual(rows[17]['items'], '40')
        self.assertEqual(rows[17]['quantity'], '1209')


class TestSpendingByCCG(ApiTestBase):
    def _get(self, params):
        params['format'] = 'csv'
        url = '/api/1.0/spending_by_ccg/'
        return self.client.get(url, params)

    def _get_rows(self, params):
        rsp = self._get(params)
        return list(csv.DictReader(rsp.content.splitlines()))

    def test_total_spending_by_ccg(self):
        rows = self._get_rows({})

        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[6]['row_id'], '03V')
        self.assertEqual(rows[6]['row_name'], 'NHS Corby')
        self.assertEqual(rows[6]['date'], '2014-09-01')
        self.assertEqual(rows[6]['actual_cost'], '38.28')
        self.assertEqual(rows[6]['items'], '41')
        self.assertEqual(rows[6]['quantity'], '1241')

    def test_total_spending_by_one_ccg(self):
        params = {
            'org': '03V',
        }
        rows = self._get_rows(params)

        rows = self._rows_from_api('/spending_by_ccg?format=csv&org=03V')
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-2]['row_id'], '03V')
        self.assertEqual(rows[-2]['row_name'], 'NHS Corby')
        self.assertEqual(rows[-2]['date'], '2014-09-01')
        self.assertEqual(rows[-2]['actual_cost'], '38.28')
        self.assertEqual(rows[-2]['items'], '41')
        self.assertEqual(rows[-2]['quantity'], '1241')

    def test_total_spending_by_multiple_ccgs(self):
        params = {
            'org': '03V,03Q',
        }
        rows = self._get_rows(params)

        rows = self._rows_from_api('/spending_by_ccg?format=csv&org=03V,03Q')
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[6]['row_id'], '03V')
        self.assertEqual(rows[6]['row_name'], 'NHS Corby')
        self.assertEqual(rows[6]['date'], '2014-09-01')
        self.assertEqual(rows[6]['actual_cost'], '38.28')
        self.assertEqual(rows[6]['items'], '41')
        self.assertEqual(rows[6]['quantity'], '1241')

    def test_spending_by_all_ccgs_on_chemical(self):
        params = {
            'code': '0202010B0',
        }
        rows = self._get_rows(params)

        rows = self._rows_from_api(
            '/spending_by_ccg?format=csv&code=0202010B0')
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]['row_id'], '03V')
        self.assertEqual(rows[0]['row_name'], 'NHS Corby')
        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '1.56')
        self.assertEqual(rows[0]['items'], '1')
        self.assertEqual(rows[0]['quantity'], '26')
        self.assertEqual(rows[5]['row_id'], '03V')
        self.assertEqual(rows[5]['row_name'], 'NHS Corby')
        self.assertEqual(rows[5]['date'], '2014-11-01')
        self.assertEqual(rows[5]['actual_cost'], '54.26')
        self.assertEqual(rows[5]['items'], '62')
        self.assertEqual(rows[5]['quantity'], '2788')

    def test_spending_by_all_ccgs_on_multiple_chemicals(self):
        params = {
            'code': '0202010B0,0202010F0',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0]['row_id'], '03Q')
        self.assertEqual(rows[0]['row_name'], 'NHS Vale of York')
        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '3.05')
        self.assertEqual(rows[0]['items'], '2')
        self.assertEqual(rows[0]['quantity'], '56')
        self.assertEqual(rows[-3]['row_id'], '03V')
        self.assertEqual(rows[-3]['row_name'], 'NHS Corby')
        self.assertEqual(rows[-3]['date'], '2014-09-01')
        self.assertEqual(rows[-3]['actual_cost'], '38.28')
        self.assertEqual(rows[-3]['items'], '41')
        self.assertEqual(rows[-3]['quantity'], '1241')

    def test_spending_by_all_ccgs_on_product(self):
        params = {
            'code': '0204000I0BC',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['row_id'], '03V')
        self.assertEqual(rows[0]['row_name'], 'NHS Corby')
        self.assertEqual(rows[0]['date'], '2014-11-01')
        self.assertEqual(rows[0]['actual_cost'], '32.26')
        self.assertEqual(rows[0]['items'], '29')
        self.assertEqual(rows[0]['quantity'], '2350')

    def test_spending_by_all_ccgs_on_presentation(self):
        params = {
            'code': '0202010B0AAABAB',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]['row_id'], '03V')
        self.assertEqual(rows[2]['row_name'], 'NHS Corby')
        self.assertEqual(rows[2]['date'], '2014-11-01')
        self.assertEqual(rows[2]['actual_cost'], '54.26')
        self.assertEqual(rows[2]['items'], '62')
        self.assertEqual(rows[2]['quantity'], '2788')

    def test_spending_by_all_ccgs_on_multiple_presentations(self):
        params = {
            'code': '0202010F0AAAAAA,0202010B0AAACAC',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]['row_id'], '03Q')
        self.assertEqual(rows[0]['row_name'], 'NHS Vale of York')
        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '3.05')
        self.assertEqual(rows[0]['items'], '2')
        self.assertEqual(rows[0]['quantity'], '56')

    def test_spending_by_all_ccgs_on_bnf_section(self):
        params = {
            'code': '2.2.1',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0]['row_id'], '03Q')
        self.assertEqual(rows[0]['row_name'], 'NHS Vale of York')
        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '3.05')
        self.assertEqual(rows[0]['items'], '2')
        self.assertEqual(rows[0]['quantity'], '56')
        self.assertEqual(rows[-1]['row_id'], '03V')
        self.assertEqual(rows[-1]['row_name'], 'NHS Corby')
        self.assertEqual(rows[-1]['date'], '2014-11-01')
        self.assertEqual(rows[-1]['actual_cost'], '54.26')
        self.assertEqual(rows[-1]['items'], '62')
        self.assertEqual(rows[-1]['quantity'], '2788')

    def test_spending_by_all_ccgs_on_multiple_bnf_sections(self):
        params = {
            'code': '2.2,2.4',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[-1]['row_id'], '03V')
        self.assertEqual(rows[-1]['row_name'], 'NHS Corby')
        self.assertEqual(rows[-1]['date'], '2014-11-01')
        self.assertEqual(rows[-1]['actual_cost'], '90.54')
        self.assertEqual(rows[-1]['items'], '95')
        self.assertEqual(rows[-1]['quantity'], '5142')


class TestSpendingByPractice(ApiTestBase):
    def _get(self, params):
        params['format'] = 'csv'
        url = '/api/1.0/spending_by_practice/'
        return self.client.get(url, params)

    def _get_rows(self, params):
        rsp = self._get(params)
        return list(csv.DictReader(rsp.content.splitlines()))

    def test_spending_by_all_practices_on_product_without_date(self):
        response = self._get({'code': '0204000I0BC'})
        self.assertEqual(response.status_code, 400)

    def test_total_spending_by_practice(self):
        params = {
            'date': '2014-11-01'
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['row_id'], 'K83059')
        self.assertEqual(rows[0]['row_name'], 'DR KHALID & PARTNERS')
        self.assertEqual(rows[0]['date'], '2014-11-01')
        self.assertEqual(rows[0]['setting'], '-1')
        self.assertEqual(rows[0]['ccg'], '03V')
        self.assertEqual(rows[0]['actual_cost'], '26.28')
        self.assertEqual(rows[0]['items'], '40')
        self.assertEqual(rows[0]['quantity'], '2543')

    def test_spending_by_practice_on_chemical(self):
        params = {
            'code': '0204000I0',
            'date': '2014-11-01'
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['row_id'], 'K83059')
        self.assertEqual(rows[0]['row_name'], 'DR KHALID & PARTNERS')
        self.assertEqual(rows[0]['setting'], '-1')
        self.assertEqual(rows[0]['ccg'], '03V')
        self.assertEqual(rows[0]['date'], '2014-11-01')
        self.assertEqual(rows[0]['actual_cost'], '14.15')
        self.assertEqual(rows[0]['items'], '16')
        self.assertEqual(rows[0]['quantity'], '1154')

    def test_spending_by_all_practices_on_chemical_with_date(self):
        params = {
            'code': '0202010F0',
            'date': '2014-09-01',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['row_id'], 'N84014')
        self.assertEqual(rows[0]['actual_cost'], '11.99')
        self.assertEqual(rows[0]['items'], '1')
        self.assertEqual(rows[0]['quantity'], '128')
        self.assertEqual(rows[1]['row_id'], 'P87629')
        self.assertEqual(rows[1]['actual_cost'], '1.99')
        self.assertEqual(rows[1]['items'], '1')
        self.assertEqual(rows[1]['quantity'], '32')

    def test_spending_by_one_practice(self):
        params = {
            'org': 'P87629',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]['row_id'], 'P87629')
        self.assertEqual(rows[-1]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[-1]['date'], '2014-11-01')
        self.assertEqual(rows[-1]['actual_cost'], '64.26')
        self.assertEqual(rows[-1]['items'], '55')
        self.assertEqual(rows[-1]['quantity'], '2599')

    def test_spending_by_two_practices_with_date(self):
        params = {
            'org': 'P87629,K83059',
            'date': '2014-11-01',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['row_id'], 'P87629')
        self.assertEqual(rows[1]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[1]['date'], '2014-11-01')
        self.assertEqual(rows[1]['actual_cost'], '64.26')
        self.assertEqual(rows[1]['items'], '55')
        self.assertEqual(rows[1]['quantity'], '2599')

    def test_spending_by_one_practice_on_chemical(self):
        params = {
            'code': '0202010B0',
            'org': 'P87629',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]['row_id'], 'P87629')
        self.assertEqual(rows[-1]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[-1]['setting'], '4')
        self.assertEqual(rows[-1]['ccg'], '03V')
        self.assertEqual(rows[-1]['date'], '2014-11-01')
        self.assertEqual(rows[-1]['actual_cost'], '42.13')
        self.assertEqual(rows[-1]['items'], '38')
        self.assertEqual(rows[-1]['quantity'], '1399')

    def test_spending_by_practice_on_multiple_chemicals(self):
        params = {
            'code': '0202010B0,0204000I0',
            'org': 'P87629,K83059',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[2]['row_id'], 'P87629')
        self.assertEqual(rows[2]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[2]['date'], '2013-10-01')
        self.assertEqual(rows[2]['actual_cost'], '1.62')
        self.assertEqual(rows[2]['items'], '1')
        self.assertEqual(rows[2]['quantity'], '24')

    def test_spending_by_all_practices_on_product(self):
        params = {
            'code': '0202010B0AA',
            'date': '2014-11-01',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['row_id'], 'K83059')
        self.assertEqual(rows[0]['actual_cost'], '12.13')
        self.assertEqual(rows[0]['items'], '24')
        self.assertEqual(rows[0]['quantity'], '1389')
        self.assertEqual(rows[1]['row_id'], 'P87629')
        self.assertEqual(rows[1]['actual_cost'], '42.13')
        self.assertEqual(rows[1]['items'], '38')
        self.assertEqual(rows[1]['quantity'], '1399')

    def test_spending_by_all_practices_on_presentation(self):
        params = {
            'code': '0202010B0AAABAB',
            'date': '2014-11-01',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['row_id'], 'K83059')
        self.assertEqual(rows[0]['actual_cost'], '12.13')
        self.assertEqual(rows[0]['items'], '24')
        self.assertEqual(rows[0]['quantity'], '1389')
        self.assertEqual(rows[1]['row_id'], 'P87629')
        self.assertEqual(rows[1]['actual_cost'], '42.13')
        self.assertEqual(rows[1]['items'], '38')
        self.assertEqual(rows[1]['quantity'], '1399')

    def test_spending_by_practice_on_presentation(self):
        params = {
            'code': '0204000I0BCAAAB',
            'org': '03V',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['row_id'], 'P87629')
        self.assertEqual(rows[1]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[1]['setting'], '4')
        self.assertEqual(rows[1]['ccg'], '03V')
        self.assertEqual(rows[1]['date'], '2014-11-01')
        self.assertEqual(rows[1]['actual_cost'], '22.13')
        self.assertEqual(rows[1]['items'], '17')
        self.assertEqual(rows[1]['quantity'], '1200')

    def test_spending_by_practice_on_multiple_presentations(self):
        params = {
            'code': '0204000I0BCAAAB,0202010B0AAABAB',
            'org': '03V',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]['row_id'], 'P87629')
        self.assertEqual(rows[2]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[2]['date'], '2014-11-01')
        self.assertEqual(rows[2]['actual_cost'], '64.26')
        self.assertEqual(rows[2]['items'], '55')
        self.assertEqual(rows[2]['quantity'], '2599')

    def test_spending_by_practice_on_section(self):
        params = {
            'code': '2',
            'org': '03V',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[-1]['row_id'], 'P87629')
        self.assertEqual(rows[-1]['row_name'], '1/ST ANDREWS MEDICAL PRACTICE')
        self.assertEqual(rows[-1]['date'], '2014-11-01')
        self.assertEqual(rows[-1]['actual_cost'], '64.26')
        self.assertEqual(rows[-1]['items'], '55')
        self.assertEqual(rows[-1]['quantity'], '2599')

    def test_spending_by_practice_on_multiple_sections(self):
        params = {
            'code': '0202,0204',
            'org': '03Q',
        }
        rows = self._get_rows(params)

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]['row_id'], 'N84014')
        self.assertEqual(rows[0]['row_name'], 'AINSDALE VILLAGE SURGERY')
        self.assertEqual(rows[0]['date'], '2013-04-01')
        self.assertEqual(rows[0]['actual_cost'], '3.05')
        self.assertEqual(rows[0]['items'], '2')
        self.assertEqual(rows[0]['quantity'], '56')


class TestAPISpendingViewsPPUTable(ApiTestBase):
    fixtures = ApiTestBase.fixtures + ['ppusavings', 'dmdproducts']

    def _get(self, **data):
        data['format'] = 'json'
        url = self.api_prefix + '/price_per_unit/'
        rsp = self.client.get(url, data, follow=True)
        return json.loads(rsp.content)

    def _expected_results(self, ids):
        # This is something of a hack; because of the SELECT DISTINCT, we
        # expect some queries to return one of two rows, but we don't know
        # which will be returned, and nor do we care.
        class Verapamil:
            def __eq__(self, other):
                return other in [
                    "Verapamil 160mg tablets",
                    "Verapamil 160mg tablets (dupe)",
                ]

        expected = [{
            "id": 1,
            "lowest_decile": 0.1,
            "presentation": "0202010F0AAAAAA",
            "name": Verapamil(),
            "price_per_unit": 0.2,
            "flag_bioequivalence": False,
            "practice": "P87629",
            "formulation_swap": None,
            "pct": "03V",
            "practice_name": "1/ST Andrews Medical Practice",
            "date": "2014-11-01",
            "quantity": 1,
            "possible_savings": 100.0,
            "price_concession": True,
        }, {
            "id": 2,
            "lowest_decile": 0.1,
            "presentation": "0202010F0AAAAAA",
            "name": Verapamil(),
            "price_per_unit": 0.2,
            "flag_bioequivalence": False,
            "practice": None,
            "formulation_swap": None,
            "pct": "03V",
            "practice_name": None,
            "date": "2014-11-01",
            "quantity": 1,
            "possible_savings": 100.0,
            "price_concession": True,
        }, {
            "id": 3,
            "lowest_decile": 0.1,
            "presentation": "0906050P0AAAFAF",
            "name": "Vitamin E 400unit capsules",
            "price_per_unit": 0.2,
            "flag_bioequivalence": False,
            "practice": "P87629",
            "formulation_swap": None,
            "pct": "03V",
            "practice_name": "1/ST Andrews Medical Practice",
            "date": "2014-11-01",
            "quantity": 1,
            "possible_savings": 100.0,
            "price_concession": False,
        }, {
            "id": 4,
            "lowest_decile": 0.1,
            "presentation": "0906050P0AAAFAF",
            "name": "Vitamin E 400unit capsules",
            "price_per_unit": 0.2,
            "flag_bioequivalence": False,
            "practice": None,
            "formulation_swap": None,
            "pct": "03V",
            "practice_name": None,
            "date": "2014-11-01",
            "quantity": 1,
            "possible_savings": 100.0,
            "price_concession": False,
        }, {
            "id": 5,
            "lowest_decile": 0.1,
            "presentation": "0202010F0AAAAAA",
            "name": Verapamil(),
            "price_per_unit": 0.2,
            "flag_bioequivalence": False,
            "practice": "N84014",
            "formulation_swap": None,
            "pct": "03Q",
            "practice_name": "Ainsdale Village Surgery",
            "date": "2014-11-01",
            "quantity": 1,
            "possible_savings": 100.0,
            "price_concession": True,
        }, {
            "id": 6,
            "lowest_decile": 0.1,
            "presentation": "0202010F0AAAAAA",
            "name": Verapamil(),
            "price_per_unit": 0.2,
            "flag_bioequivalence": False,
            "practice": None,
            "formulation_swap": None,
            "pct": "03Q",
            "practice_name": None,
            "date": "2014-11-01",
            "quantity": 1,
            "possible_savings": 100.0,
            "price_concession": True,
        }]

        return [r for r in expected if r['id'] in ids]

    def test_bnf_code(self):
        data = self._get(bnf_code='0202010F0AAAAAA', date='2014-11-01')
        data.sort(key=lambda r: r['id'])
        self.assertEqual(data, self._expected_results([1, 2, 5, 6]))

    def test_bnf_code_no_data_for_month(self):
        data = self._get(bnf_code='0202010F0AAAAAA', date='2014-12-01')
        self.assertEqual(len(data), 0)

    def test_invalid_bnf_code(self):
        data = self._get(bnf_code='XYZ', date='2014-11-01')
        self.assertEqual(data, {'detail': 'Not found.'})

    def test_entity_code_practice(self):
        data = self._get(entity_code='P87629', date='2014-11-01')
        data.sort(key=lambda r: r['id'])
        self.assertEqual(data, self._expected_results([1, 3]))

    def test_entity_code_practice_no_data_for_month(self):
        data = self._get(entity_code='P87629', date='2014-12-01')
        self.assertEqual(len(data), 0)

    def test_invalid_entity_code_practice(self):
        data = self._get(entity_code='P00000', date='2014-11-01')
        self.assertEqual(data, {'detail': 'Not found.'})

    def test_entity_code_ccg(self):
        data = self._get(entity_code='03V', date='2014-11-01')
        data.sort(key=lambda r: r['id'])
        self.assertEqual(data, self._expected_results([2, 4]))

    def test_entity_code_ccg_and_bnf_code(self):
        data = self._get(entity_code='03V', bnf_code='0202010F0AAAAAA',
                         date='2014-11-01')
        self.assertEqual(data, self._expected_results([1]))

    def test_entity_code_ccg_no_data_for_month(self):
        data = self._get(entity_code='03V', date='2014-12-01')
        self.assertEqual(len(data), 0)

    def test_invalid_entity_code_ccg(self):
        data = self._get(entity_code='000', date='2014-11-01')
        self.assertEqual(data, {'detail': 'Not found.'})


class TestAPISpendingViewsPPUBubble(ApiTestBase):
    fixtures = ApiTestBase.fixtures + ['importlog']

    def test_simple(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0204000I0BCAAAB&date=2014-11-01&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertEqual(len(data['series']), 1)  # Only Trandate prescribed
        self.assertEqual(len([x for x in data if x[1]]), 3)

    def test_date(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0204000I0BCAAAB&date=2000-01-01&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertEqual(len(data['series']), 0)

    def test_highlight(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0204000I0BCAAAB&date=2014-11-01&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        # N.B. This is the mean of a *single* value; although there
        # are two values in the raw data, one is trimmed as it is
        # outside the 99th percentile
        self.assertEqual(data['plotline'], 0.0325)

    def test_code_without_matches(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0204000I0BCAAAX&date=2014-11-01&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertIsNone(data['plotline'])

    def test_focus(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0202010F0AAAAAA&date=2014-09-01'
        url += '&highlight=03V&focus=1'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertEqual(
            data,
            {'series': [
                {'y': 0.09, 'x': 1, 'z': 32.0,
                 'name': 'Chlortalidone_Tab 50mg',
                 'mean_ppu': 0.09}],
             'categories': [
                 {'is_generic': True, 'name': 'Chlortalidone_Tab 50mg'}],
             'plotline': 0.08875}
        )

    def test_no_focus(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0202010F0AAAAAA&date=2014-09-01'
        url += '&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertEqual(
            data,
            {'series': [
                {'y': 0.09, 'x': 1, 'z': 32.0,
                 'name': 'Chlortalidone_Tab 50mg',
                 'mean_ppu': 0.095},
                {'y': 0.1, 'x': 1, 'z': 128.0,
                 'name': 'Chlortalidone_Tab 50mg',
                 'mean_ppu': 0.095}],
             'categories': [
                 {'is_generic': True, 'name': 'Chlortalidone_Tab 50mg'}],
             'plotline': 0.08875}
        )

    def test_trim(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0202010F0AAAAAA&date=2014-09-01'
        url += '&highlight=03V&trim=1'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertEqual(
            data,
            {'series': [
                {'y': 0.09, 'x': 1, 'z': 32.0,
                 'name': 'Chlortalidone_Tab 50mg',
                 'mean_ppu': 0.095}],
             'categories': [
                 {'is_generic': True, 'name': 'Chlortalidone_Tab 50mg'}],
             'plotline': 0.08875}
        )


class TestAPISpendingViewsPPUWithGenericMapping(ApiTestBase):
    fixtures = ApiTestBase.fixtures + ['importlog', 'genericcodemapping']

    def test_with_wildcard(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0204000I0BCAAAB&date=2014-11-01&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        # Expecting the total to be quite different
        self.assertEqual(data['plotline'], 0.0315505963832243)
        # Bendroflumethiazide and Trandate:
        self.assertEqual(len(data['series']), 2)

    def test_with_specific(self):
        url = '/bubble?format=json'
        url += '&bnf_code=0204000I0BCAAAX&date=2014-11-01&highlight=03V'
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        data = json.loads(response.content)
        self.assertEqual(data['plotline'], 0.0325)
