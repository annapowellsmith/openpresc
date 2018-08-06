#!/usr/bin/env python
import os
import sys

import dotenv

if __name__ == "__main__":
    # We can't do read_dotenv('../environment') because that assumes that when
    # manage.py we are in its current directory, which isn't the case for cron
    # jobs.
    env_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        '..', 'environment'
    )

    dotenv.read_dotenv(env_path)

    if 'DJANGO_SETTINGS_MODULE' not in os.environ:
        if len(sys.argv) > 1 and sys.argv[1] in ['test', 'pipeline_e2e_tests']:
            settings = 'test'
        else:
            settings = 'local'
        os.environ["DJANGO_SETTINGS_MODULE"] = (
            "openprescribing.settings.%s" % settings)

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
