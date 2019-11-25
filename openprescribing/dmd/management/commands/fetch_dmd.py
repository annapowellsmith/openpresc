"""
Downloads and unzips the latest dm+d data to
PIPELINE_DATA_BASEDIR/dmd/[yyyy_mm_dd]/[release]/

Does nothing if file already downloaded.
"""

import glob
import os
import zipfile
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from django.conf import settings
from django.core.management import BaseCommand

from openprescribing.utils import mkdir_p


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **kwargs):
        base_url = "https://isd.digital.nhs.uk/"
        session = requests.Session()

        login_url = base_url + "trud3/security/j_spring_security_check"
        params = {
            "j_username": settings.TRUD_USERNAME,
            "j_password": settings.TRUD_PASSWORD,
            "commit": "LOG+IN",
        }
        rsp = session.post(login_url, params)

        index_url = (
            base_url + "trud3/user/authenticated/group/0/pack/6/subpack/24/releases"
        )
        rsp = session.get(index_url)

        doc = BeautifulSoup(rsp.text, "html.parser")
        latest_release_div = doc.find("div", class_="release")
        p = latest_release_div.find_all("p")[1]
        text = " ".join(p.text.splitlines()).strip()
        release_date = datetime.strptime(text, "Released on %A, %d %B %Y").strftime(
            "%Y_%m_%d"
        )
        download_href = latest_release_div.find("a", class_="download-release")["href"]
        filename = download_href.split("/")[-1]

        dir_path = os.path.join(settings.PIPELINE_DATA_BASEDIR, "dmd", release_date)
        zip_path = os.path.join(dir_path, filename)
        unzip_dir_path = os.path.join(dir_path, os.path.splitext(filename)[0])

        if os.path.exists(zip_path):
            return

        rsp = session.get(base_url + download_href, stream=True)

        mkdir_p(dir_path)

        with open(zip_path, "wb") as f:
            for block in rsp.iter_content(32 * 1024):
                f.write(block)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(unzip_dir_path)

        for nested_zip_path in glob.glob(os.path.join(unzip_dir_path, "*.zip")):
            with zipfile.ZipFile(nested_zip_path) as zf:
                zf.extractall(unzip_dir_path)
