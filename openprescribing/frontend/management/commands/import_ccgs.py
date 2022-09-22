import csv
from django.core.management.base import BaseCommand
from frontend.models import PCT, STP


class Command(BaseCommand):
    help = "Imports CCG/PCT names and details from HSCIC organisational data. "
    help += "You should import CCG boundaries BEFORE running this."  # Why?!

    def add_arguments(self, parser):
        parser.add_argument("--ccg")

    def handle(self, **options):
        for row in csv.reader(open(options["ccg"], "rU")):
            row = [r.strip() for r in row]
            if row[2] == "Y99" or row[3] == "Q99":
                # This indicates a National Commissioning Hub which does not
                # belong to a region, and which in any case we ignore.
                continue

            ccg, created = PCT.objects.get_or_create(code=row[0])
            if created:
                ccg.name = row[1]
            ccg.regional_team_id = row[2]
            ccg.stp = STP.objects.get_or_create(code=row[3], name=f"ICB {row[3]}")[0]
            ccg.address = ", ".join([r for r in row[4:9] if r])
            ccg.postcode = row[9]
            od = row[10]
            ccg.open_date = od[:4] + "-" + od[4:6] + "-" + od[-2:]
            cd = row[11]
            if cd:
                ccg.close_date = cd[:4] + "-" + cd[4:6] + "-" + cd[-2:]
            if row[13] == "C":
                ccg.org_type = "CCG"
            ccg.save()
