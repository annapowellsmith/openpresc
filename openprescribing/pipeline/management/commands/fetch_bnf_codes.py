import datetime
import glob
import os
import zipfile
from argparse import RawTextHelpFormatter

import requests
from django.conf import settings
from django.core.management import BaseCommand
from lxml import html

from openprescribing.utils import mkdir_p


class Command(BaseCommand):
    help = """
This command downloads the latest BNF codes.

The BNF codes are in a compressed CSV file that is on a site that is protected
by a captcha.  To download the file, you will need to solve the captcha in your
browser.  This will set a cookie in your browser which you will need to pass to
this command.

Specifically, you should:

    * Visit https://applications.nhsbsa.nhs.uk/infosystems/data/showDataSelector.do?reportId=126 in your browser
    * Solve the captcha and click on "Guest Login"
    * Copy the value of the JSESSIONID cookie
      * In Chrome, this can be found in the Application tab of Developer Tools
    * Run `./manage.py fetch_bnf_codes [cookie]`
    """.strip()

    def create_parser(self, *args, **kwargs):
        parser = super(Command, self).create_parser(*args, **kwargs)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_arguments(self, parser):
        parser.add_argument("jsessionid")

    def handle(self, *args, **kwargs):
        path = os.path.join(settings.PIPELINE_DATA_BASEDIR, "bnf_codes")
        year_and_month = datetime.date.today().strftime("%Y_%m")
        dir_path = os.path.join(path, year_and_month)
        mkdir_p(dir_path)
        zip_path = os.path.join(dir_path, "download.zip")

        base_url = "https://applications.nhsbsa.nhs.uk/infosystems/data/"

        session = requests.Session()
        session.cookies["JSESSIONID"] = kwargs["jsessionid"]

        url = base_url + "showDataSelector.do"
        params = {"reportId": "126"}
        rsp = session.get(url, params=params)

        tree = html.fromstring(rsp.content)
        options = tree.xpath('//select[@id="bnfVersion"]/option')

        year_to_bnf_version = {}
        for option in options:
            datestamp, version = option.text.split(" : ")
            date = datetime.datetime.strptime(datestamp, "%d-%m-%Y")
            year_to_bnf_version[date.year] = version

        year = max(year_to_bnf_version)
        version = year_to_bnf_version[year]

        url = base_url + "requestSelectedDownload.do"
        params = {
            "bnfVersion": version,
            "filePath": "",
            "dataView": "260",
            "format": "",
            "defaultReportIdDataSel": "",
            "reportId": "126",
            "action": "checkForAvailableDownload",
        }
        rsp = session.get(url, params=params)

        request_id = rsp.json()["requestNo"]

        url = base_url + "downloadAvailableReport.zip"
        params = {"requestId": request_id}
        rsp = session.post(url, params=params)
        with open(zip_path, "wb") as f:
            f.write(rsp.content)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dir_path)

        csv_paths = glob.glob(os.path.join(dir_path, "*.csv"))

        assert len(csv_paths) == 1

        os.rename(csv_paths[0], os.path.join(dir_path, "bnf_codes.csv"))
