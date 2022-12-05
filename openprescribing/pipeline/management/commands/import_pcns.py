from django.core.management import BaseCommand
from django.db import transaction
from frontend.models import PCN, Practice
from openpyxl import load_workbook


class Command(BaseCommand):
    help = "This command imports PCNs and PCN mappings"

    def add_arguments(self, parser):
        parser.add_argument("--filename")

    def handle(self, *args, **kwargs):
        workbook = load_workbook(kwargs["filename"])

        details_sheet = workbook.get_sheet_by_name("PCNDetails")
        members_sheet = workbook.get_sheet_by_name("PCN Core Partner Details")
        pcn_details = {}
        for code, name in self.get_pcn_details_from_sheet(details_sheet):
            pcn_details[code] = {"name": name, "members": set()}
        for practice_code, pcn_code in self.get_pcn_members_from_sheet(members_sheet):
            pcn_details[pcn_code]["members"].add(practice_code)

        with transaction.atomic():
            for code, details in pcn_details.items():
                PCN.objects.update_or_create(
                    code=code, defaults={"name": details["name"]}
                )
                Practice.objects.filter(code__in=details["members"]).update(pcn=code)

    def get_pcn_details_from_sheet(self, sheet):
        rows = ([cell.value for cell in row] for row in sheet.rows)
        headers = next(rows)

        CODE_COL = headers.index("PCN Code")
        NAME_COL = headers.index("PCN Name")

        for n, row in enumerate(rows, start=2):
            code = row[CODE_COL]
            name = row[NAME_COL]
            # Skip blank lines
            if not code and not name:
                continue
            if not code or not name:
                raise ValueError("Blank code or name on row {}".format(n))
            yield code, name

    def get_pcn_members_from_sheet(self, sheet):
        rows = ([cell.value for cell in row] for row in sheet.rows)
        headers = next(rows)

        PRACTICE_COL = headers.index("Partner\nOrganisation\nCode")
        PCN_COL = headers.index("PCN Code")
        END_DATE_COL = headers.index("Practice to PCN\nRelationship\nEnd Date")

        for n, row in enumerate(rows, start=2):
            practice_code = row[PRACTICE_COL]
            pcn_code = row[PCN_COL]
            end_date = row[END_DATE_COL]
            # Skip blank lines
            if not practice_code and not pcn_code:
                continue
            if not practice_code or not pcn_code:
                raise ValueError("Blank code on row {}".format(n))
            # Skip relationships that have ended
            if end_date:
                continue
            yield practice_code, pcn_code
