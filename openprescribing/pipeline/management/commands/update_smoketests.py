import os
import glob
import json

from django.conf import settings
from django.core.management import BaseCommand

from ...cloud_utils import CloudHandler


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('last_imported')

    def handle(self, *args, **kwargs):
        smoketest_handler = SmokeTestHandler()
        smoketest_handler.update_smoketests(kwargs['last_imported'])
        print('You should now commit the updated smoketest files')
        raw_input('Press enter to continue')


class SmokeTestHandler(CloudHandler):
    def update_smoketests(self, last_imported):
        prescribing_date = "-".join(last_imported.split('_')) + '-01'
        date_condition = ('month > TIMESTAMP(DATE_SUB(DATE "%s", '
                          'INTERVAL 5 YEAR))' % prescribing_date)

        path = os.path.join(settings.PIPELINE_METADATA_DIR, 'smoketests')
        for sql_file in glob.glob(os.path.join(path, '*.sql')):
            test_name = os.path.splitext(
                os.path.basename(sql_file))[0]
            with open(sql_file, 'rb') as f:
                query = f.read().replace(
                    '{{ date_condition }}', date_condition)
                print(query)
                response = self.bigquery.jobs().query(
                    projectId='ebmdatalab',
                    body={'useLegacySql': False,
                          'timeoutMs': 20000,
                          'query': query}).execute()
                quantity = []
                cost = []
                items = []
                for r in self.rows_to_dict(response):
                    quantity.append(r['quantity'])
                    cost.append(r['actual_cost'])
                    items.append(r['items'])
                print("Updating test expectations for %s" % test_name)
                json_path = os.path.join(path, '%s.json' % test_name)
                with open(json_path, 'wb') as f:
                    obj = {'cost': cost,
                           'items': items,
                           'quantity': quantity}
                    json.dump(obj, f, indent=2)
