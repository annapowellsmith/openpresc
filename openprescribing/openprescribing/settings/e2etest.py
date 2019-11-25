from .test import *

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": utils.get_env_setting("E2E_DB_NAME"),
        "USER": utils.get_env_setting("DB_USER"),
        "PASSWORD": utils.get_env_setting("DB_PASS"),
        "HOST": utils.get_env_setting("DB_HOST", "127.0.0.1"),
    }
}

PIPELINE_METADATA_DIR = os.path.join(APPS_ROOT, "pipeline", "metadata")

PIPELINE_DATA_BASEDIR = os.path.join(APPS_ROOT, "pipeline", "e2e-test-data", "data", "")

PIPELINE_IMPORT_LOG_PATH = os.path.join(
    APPS_ROOT, "pipeline", "e2e-test-data", "log.json"
)

SLACK_SENDING_ACTIVE = True

BQ_DEFAULT_TABLE_EXPIRATION_MS = 24 * 60 * 60 * 1000  # 24 hours

# We want to use the real measure definitions, not the test ones!
MEASURE_DEFINITIONS_PATH = os.path.join(APPS_ROOT, "measure_definitions")
