import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


SECRET_KEY = required_env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in required_env("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()]
EMPLOYEE_EMAIL_DOMAINS = tuple(
    domain.strip().lower().lstrip("@")
    for domain in os.environ.get("EMPLOYEE_EMAIL_DOMAINS", "wdn.com.np").split(",")
    if domain.strip()
)
if not EMPLOYEE_EMAIL_DOMAINS:
    raise RuntimeError("At least one employee email domain is required")
HTTPS_ENABLED = os.environ.get("DJANGO_HTTPS", "false").lower() == "true"
PUBLIC_BASE_URL = os.environ.get("DJANGO_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
public_url = urlsplit(PUBLIC_BASE_URL)
if (
    public_url.scheme not in {"http", "https"}
    or not public_url.hostname
    or public_url.username
    or public_url.password
    or public_url.path
    or public_url.query
    or public_url.fragment
    or public_url.hostname not in ALLOWED_HOSTS
):
    raise RuntimeError("DJANGO_PUBLIC_BASE_URL must be an origin whose hostname is in DJANGO_ALLOWED_HOSTS")
if HTTPS_ENABLED and public_url.scheme != "https":
    raise RuntimeError("HTTPS deployment requires an HTTPS DJANGO_PUBLIC_BASE_URL")
if HTTPS_ENABLED and ("*" in ALLOWED_HOSTS or len(SECRET_KEY) < 50):
    raise RuntimeError(
        "HTTPS deployment requires explicit allowed hosts and a secret key of at least 50 characters"
    )
AUTH_TRUSTED_PROXY_CIDRS = tuple(
    value.strip() for value in os.environ.get("AUTH_TRUSTED_PROXY_CIDRS", "").split(",") if value.strip()
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "booking",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "booking.middleware.LocalNullOriginMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "booking.middleware.ApplicationSafetyMiddleware",
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
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required_env("POSTGRES_DB"),
        "USER": required_env("POSTGRES_USER"),
        "PASSWORD": required_env("POSTGRES_PASSWORD"),
        "HOST": required_env("POSTGRES_HOST"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    }
}

AUTH_USER_MODEL = "booking.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_RESET_TIMEOUT = 3600

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_SSL_REDIRECT = HTTPS_ENABLED
SECURE_REDIRECT_EXEMPT = [r"^healthz/$", r"^livez/$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if HTTPS_ENABLED else None
SESSION_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_USE_SESSIONS = True
CSRF_FAILURE_VIEW = "booking.views.csrf_failure"
SECURE_HSTS_SECONDS = 3600 if HTTPS_ENABLED else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "no-referrer"

MAIL_MODE = os.environ.get("DJANGO_EMAIL_BACKEND", "disabled").lower()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_FROM = os.environ.get("DJANGO_FROM_EMAIL", "").strip()
EMAIL_READY = False
if MAIL_MODE == "smtp":
    EMAIL_HOST = SMTP_HOST
    EMAIL_PORT = int(os.environ.get("SMTP_PORT", "587"))
    if not 1 <= EMAIL_PORT <= 65535:
        raise RuntimeError("SMTP_PORT must be between 1 and 65535")
    EMAIL_HOST_USER = os.environ.get("SMTP_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    EMAIL_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
    if EMAIL_USE_TLS and EMAIL_USE_SSL:
        raise RuntimeError("Choose either SMTP_USE_TLS or SMTP_USE_SSL")
    EMAIL_TIMEOUT = 10
    DEFAULT_FROM_EMAIL = SMTP_FROM
    EMAIL_READY = bool(SMTP_HOST and SMTP_FROM)
    EMAIL_BACKEND = (
        "django.core.mail.backends.smtp.EmailBackend"
        if EMAIL_READY
        else "booking.mail_backends.DisabledEmailBackend"
    )
elif MAIL_MODE == "file" and not HTTPS_ENABLED:
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = "/tmp/meeting-room-mail"
    DEFAULT_FROM_EMAIL = "Meeting Rooms <noreply@local.invalid>"
    EMAIL_READY = True
elif MAIL_MODE == "disabled":
    EMAIL_BACKEND = "booking.mail_backends.DisabledEmailBackend"
    DEFAULT_FROM_EMAIL = "Meeting Rooms <noreply@local.invalid>"
else:
    raise RuntimeError("DJANGO_EMAIL_BACKEND must be disabled, smtp, or file (local HTTP development only)")

if not EMAIL_READY:
    logging.getLogger("booking.configuration").warning(
        "Email is unconfigured; sign-in email and notification delivery are unavailable until SMTP is supplied"
    )

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"safe": {"format": "{levelname} {name}: {message}", "style": "{"}},
    "filters": {"safe_request": {"()": "booking.logging.SafeRequestLogFilter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "safe"},
        "safe_request": {"class": "logging.StreamHandler", "formatter": "safe", "filters": ["safe_request"]},
    },
    "loggers": {
        "booking": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["safe_request"], "level": "WARNING", "propagate": False},
        "django.server": {"handlers": ["safe_request"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["safe_request"], "level": "WARNING", "propagate": False},
    },
}
