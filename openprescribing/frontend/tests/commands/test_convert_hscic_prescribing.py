import csv
import os
import tempfile

from google.cloud import storage
from mock import MagicMock
from mock import patch

from django.core.management import call_command
from django.test import TestCase

from frontend.management.commands.convert_hscic_prescribing import Command
from django.core.management.base import CommandError


class CommandsTestCase(TestCase):

    def test_convert_legacy_hscic_prescribing(self):
        args = []
        test_file = 'frontend/tests/fixtures/commands/'
        test_file += 'hscic_prescribing_sample.csv'
        opts = {
            'filename': test_file,
            'is_test': True
        }
        call_command('convert_hscic_prescribing', *args, **opts)

        test_output = 'frontend/tests/fixtures/commands/'
        test_output += 'hscic_prescribing_sample_test.CSV'
        reader = csv.reader(open(test_output, 'rU'))
        rows = []
        for row in reader:
            rows.append(row)

        os.remove(test_output)
        self.assertEqual(len(rows), 51)

        # Test the basics are in the order expected by our COPY statement:
        # pct_id,practice_id,presentation_code,
        # total_items,net_cost,actual_cost,
        # quantity,processing_date,price_per_unit
        self.assertEqual(rows[0][0], 'RXA')
        self.assertEqual(rows[0][1], 'N81646')
        self.assertEqual(rows[0][2], '0102000N0AAABAB')
        self.assertEqual(rows[0][3], '1')
        self.assertEqual(rows[0][4], '0.64')
        self.assertEqual(rows[0][5], '0.7')
        self.assertEqual(rows[0][6], '12')
        self.assertEqual(rows[0][7], '2014-10-01')

    @patch('frontend.management.commands.convert_hscic_prescribing.Command'
           '.aggregate_nhs_digital_data')
    def test_convert_detailed_hscic_prescribing_call(self, method):
        method.return_value = 'filename.csv'
        opts = {
            'filename': ('/home/hello/openprescribing-data/data/prescribing'
                         '/2017_03/Detailed_Prescribing_Information.csv')
        }
        call_command('convert_hscic_prescribing', **opts)
        method.assert_called_with(
            ('gs://ebmdatalab/hscic/prescribing/2017_03/'
             'Detailed_Prescribing_Information.csv'),
            ('/home/hello/openprescribing-data/data/prescribing'
             '/2017_03/Detailed_Prescribing_Information_formatted.CSV'),
            '2017_03_01')

    @patch('frontend.management.commands.convert_hscic_prescribing.Command'
           '.aggregate_nhs_digital_data')
    def test_convert_detailed_hscic_prescribing_has_date(self, method):
        opts = {
            'filename': ('/home/hello/openprescribing-data/data/prescribing'
                         '/Detailed_Prescribing_Information.csv')
        }
        with self.assertRaises(CommandError):
            call_command('convert_hscic_prescribing', **opts)


@patch('frontend.management.commands.convert_hscic_prescribing'
       '.TEMP_SOURCE_NAME', 'temp_raw_nhs_digital_data')
@patch('frontend.management.commands.convert_hscic_prescribing'
       '.Command.assert_latest_data_not_already_uploaded', MagicMock())
class AggregateTestCase(TestCase):
    """Test that data in the "detailed" format is correctly aggregated to
    the level we currently use in the website.

    The source format has one iine for each presentation *and pack
    size*, so prescriptions of 28 paracetamol will be on a separate
    line from prescriptions of 100 paracetamol.

    The destination format has one line for paracetamol of any pack
    size.

    """
    def setUp(self):
        # upload a file to GCS
        # test that the file we get back is correct
        test_file = 'frontend/tests/fixtures/commands/'
        test_file += 'Detailed_Prescribing_Information.csv'
        bucket_name = 'ebmdatalab'
        object_name = 'test_hscic/prescribing/sample.csv'
        client = storage.client.Client(project='ebmdatalab')
        bucket = client.get_bucket(bucket_name)
        blob = storage.Blob(object_name, bucket)

        with open(test_file, 'rb') as my_file:
            blob.upload_from_file(my_file)
        self.gcs_uri = "gs://ebmdatalab/%s" % object_name

    def test_data_is_aggregated(self):
        target = tempfile.NamedTemporaryFile(mode='r+')
        cmd = Command()
        cmd.is_test = True
        cmd.aggregate_nhs_digital_data(
            self.gcs_uri, target.name, date='2016_01_01')
        target.seek(0)
        rows = list(csv.reader(open(target.name, 'rU')))
        # there are 11 rows in the input file; 2 are for the same
        # practice/presentation and should be collapsed, and 1 is for
        # an UNKNONWN SURGERY (see issue #349)
        self.assertEqual(len(rows), 9)
        dr_chan = next(
            x for x in rows if x[1] == 'P92042' and x[2] == '0202010B0AAABAB')
        self.assertEqual(int(dr_chan[6]), 1288)  # combination of two rows
