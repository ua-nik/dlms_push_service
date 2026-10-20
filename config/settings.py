"""
Django settings for NIK DLMS Push Service.
"""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Ensure apps directory is on python path
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "apps"))

# -----------------------------------------------------------------------------
# Security & Debug
# -----------------------------------------------------------------------------
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY", "insecure-default-change-in-production-random-key"
)
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in ("true", "1", "t", "yes")

allowed_hosts_str = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_str.split(",") if h.strip()]

# -----------------------------------------------------------------------------
# Application definition
# -----------------------------------------------------------------------------
INSTALLED_APPS = [
    # Daphne must be listed before django.contrib.staticfiles
    "daphne",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party apps
    "rest_framework",
    "drf_spectacular",
    "channels",
    # Local apps
    "apps.core.apps.CoreConfig",
    "apps.meters.apps.MetersConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# -----------------------------------------------------------------------------
# Database configuration (PostgreSQL)
# -----------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "dlms_push_db"),
        "USER": os.getenv("DB_USER", "dlms_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", "dlms_password"),
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------------
# Channels & Redis configuration
# -----------------------------------------------------------------------------
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", "6379"))

use_inmemory_channel = os.getenv("USE_INMEMORY_CHANNEL_LAYER", "False").lower() in ("true", "1", "yes")
if "test" in sys.argv or use_inmemory_channel:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(redis_host, redis_port)],
            },
        },
    }

# -----------------------------------------------------------------------------
# REST Framework & OpenAPI Documentation
# -----------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "NIK DLMS Push Service API",
    "DESCRIPTION": (
        "REST API та WebSocket сервіс для прийому, збереження та передачі "
        "DLMS Push-повідомлень лічильників NIK мобільним додаткам "
        "NIK BT-DLMS (Android / iOS)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# -----------------------------------------------------------------------------
# Password validation & Internationalization
# -----------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"
    },
]

LANGUAGE_CODE = "uk"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# -----------------------------------------------------------------------------
# DLMS Push Service Settings
# -----------------------------------------------------------------------------
# UDP receiver settings
UDP_RECEIVER_HOST = os.getenv("UDP_RECEIVER_HOST", "0.0.0.0")
UDP_RECEIVER_PORT = int(os.getenv("UDP_RECEIVER_PORT", "4059"))
UDP_RECEIVER_QUEUE_SIZE = int(os.getenv("UDP_RECEIVER_QUEUE_SIZE", "10000"))
UDP_RECEIVER_WORKERS = int(os.getenv("UDP_RECEIVER_WORKERS", "4"))
UDP_SOCKET_RCVBUF_BYTES = int(os.getenv("UDP_SOCKET_RCVBUF_BYTES", "4194304"))

# DLMS Crypto Keys
DLMS_DEFAULT_GLOBAL_KEY = os.getenv(
    "DLMS_DEFAULT_GLOBAL_KEY", "MYDUMMYGLOBALKEY"
)
DLMS_DEFAULT_AUTH_KEY = os.getenv("DLMS_DEFAULT_AUTH_KEY", "MYDUMMYGLOBALKEY")

# Individual meter keys JSON mapping
try:
    DLMS_METER_KEYS_MAP = json.loads(os.getenv("DLMS_METER_KEYS_JSON", "{}"))
except Exception:
    DLMS_METER_KEYS_MAP = {}


# -----------------------------------------------------------------------------
# Logging configuration
# -----------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)-8s [%(name)s:%(lineno)d] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": sys.stdout,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps.meters": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "apps.core": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

# Keep every received meter reading unless explicitly disabled.

# Explicit opt-in for unauthenticated DLMS notifications.
DLMS_ALLOW_UNENCRYPTED = os.getenv("DLMS_ALLOW_UNENCRYPTED", "False").lower() in ("true", "1", "yes")
