"""Production settings and globals."""

from __future__ import absolute_import
from .base import *
from common import utils


# HOST CONFIGURATION
# See:
# https://docs.djangoproject.com/en/1.5/releases/1.5/#allowed-hosts-required-in-production
ALLOWED_HOSTS = ['openprescribing.net',
                 'deploy.openprescribing.net',
                 'openprescriptions.net']
# END HOST CONFIGURATION

# See: https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = '[%s] ' % SITE_NAME

# END EMAIL CONFIGURATION

# DATABASE CONFIGURATION
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': utils.get_env_setting('DB_NAME'),
        'USER': utils.get_env_setting('DB_USER'),
        'PASSWORD': utils.get_env_setting('DB_PASS'),
        'HOST': utils.get_env_setting('DB_HOST', '127.0.0.1')
    },
    'old': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': utils.get_env_setting('DB_NAME'),
        'USER': utils.get_env_setting('DB_USER'),
        'PASSWORD': utils.get_env_setting('DB_PASS'),
        'HOST': utils.get_env_setting('DB_HOST', '138.68.140.164')
    }

}
# END DATABASE CONFIGURATION


# CACHE CONFIGURATION
# See: https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
# END CACHE CONFIGURATION

GOOGLE_TRACKING_ID = 'UA-62480003-1'

ANYMAIL["MAILGUN_SENDER_DOMAIN"] = "openprescribing.net",

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': ('%(asctime)s %(levelname)s [%(name)s:%(lineno)s] '
                       '%(module)s %(process)d %(thread)d %(message)s')
        }
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        }
    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler'
        },
        'gunicorn': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': "%s/logs/gunicorn.log" % INSTALL_ROOT,
            'maxBytes': 1024 * 1024 * 100,  # 100 mb
        },
        'signals': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': "%s/logs/mail-signals.log" % INSTALL_ROOT,
            'maxBytes': 1024 * 1024 * 100,  # 100 mb
        }

    },
    'loggers': {
        'django': {
            'handlers': ['gunicorn'],
            'level': 'WARN',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
        'frontend': {
            'level': 'WARN',
            'handlers': ['gunicorn'],
            'propagate': True,
        },
        'frontend.signals.handlers': {
            'level': 'DEBUG',
            'handlers': ['signals'],
            'propagate': False,
        },
    }
}
