import csv

from django.http import Http404
from django.test import TestCase

from frontend.models import Prescription, ImportLog

from matrixstore.tests.decorators import copy_fixtures_to_matrixstore


@copy_fixtures_to_matrixstore
class ApiTestBase(TestCase):
    """Base test case that sets up all the fixtures required by any of the
    API tests.

    """

    fixtures = [
        "orgs",
        "practices",
        "practice_listsizes",
        "products",
        "presentations",
        "sections",
        "prescriptions",
        "chemicals",
    ]
    api_prefix = "/api/1.0"

    @classmethod
    def setUpTestData(cls):
        # Create an ImportLog entry for the latest prescribing date we have
        date = Prescription.objects.latest("processing_date").processing_date
        ImportLog.objects.create(current_at=date, category="prescribing")

    def _rows_from_api(self, url):
        url = self.api_prefix + url
        response = self.client.get(url, follow=True)
        if response.status_code == 404:
            raise Http404("URL %s does not exist" % url)
        reader = csv.DictReader(response.content.decode("utf8").splitlines())
        rows = []
        for row in reader:
            rows.append(row)
        return rows
