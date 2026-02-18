"""
Django settings for emdcbackend project.

This file is written to work for:
- Local development (DEBUG=True, .local.env)
- Production (DEBUG=False, env vars via hosting platform or .prod.env)

"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ============================================================================
# Environment loading
# ============================================================================

env_path = BASE_DIR / ".local.env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            v = v.strip()
            # Strip quotes if present
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


# ============================================================================
# Helper for env booleans
# ============================================================================

def _env_bool(name: str, default: bool) -> bool:
    """
    Read a boolean from environment variables.

    Examples:
      DEBUG=1 / "true" / "yes"  → True
      DEBUG=0 / "false" / "no"  → False
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes")


# ============================================================================
# Core security / debug
# ============================================================================

# In PROD: DJANGO_SECRET_KEY **must** be set via env.
# In DEV: you can rely on .local.env or the default here .
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-me")

# DEBUG:
#   - In dev: DEBUG=True
#   - In prod: set DEBUG=0 in environment (or remove .local.env which sets it)
DEBUG = _env_bool("DEBUG", default=True)

# ALLOWED_HOSTS:


_default_hosts = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "django-api",
]

_allowed_hosts_env = os.getenv("ALLOWED_HOSTS")

if _allowed_hosts_env is not None:
    # environment variable overrides AND can extend defaults
    env_hosts = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]
    ALLOWED_HOSTS = list(set(_default_hosts + env_hosts))
else:
    ALLOWED_HOSTS = _default_hosts if DEBUG else [
        "0.0.0.0",
        "localhost",
        "127.0.0.1",
        "emdc-django-api",
        "api.emdcresults.com",
        "emdcresults.com",
        "www.emdcresults.com",
      
    ]


# ============================================================================
# Cookie / session / CSRF configuration
# ============================================================================

# Session lifetime (3 hours)
SESSION_COOKIE_AGE = 10800

# SAMESITE
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax" if DEBUG else "None"

# Secure flag:
# - In dev over HTTP: set to False (default when DEBUG=True).
# - In prod over HTTPS: set to True (default when DEBUG=False).
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", default=not DEBUG)

# HTTPOnly:
SESSION_COOKIE_HTTPONLY = _env_bool("SESSION_COOKIE_HTTPONLY", default=True)
CSRF_COOKIE_HTTPONLY = _env_bool("CSRF_COOKIE_HTTPONLY", default=False)

# Cookie domain:
if not DEBUG:
    SESSION_COOKIE_DOMAIN = ".emdcresults.com"
    CSRF_COOKIE_DOMAIN = ".emdcresults.com"
else:
    SESSION_COOKIE_DOMAIN = None
    CSRF_COOKIE_DOMAIN = None


# ============================================================================
# CORS / CSRF domains
# ============================================================================

CORS_ALLOW_CREDENTIALS = True

if DEBUG:
    # DEV: allow your local frontends.
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:7001",
        "http://127.0.0.1:7001",
        "http://localhost:5173",   
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:7001",
        "http://127.0.0.1:7001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]
else:
    # PROD: only allow your deployed frontend(s).
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "https://emdcresults.com",
        "https://www.emdcresults.com",
    ]

    CSRF_TRUSTED_ORIGINS = [
        "https://emdcresults.com",
        "https://www.emdcresults.com",
        "https://api.emdcresults.com",
    ]


# ============================================================================
# Installed apps
# ============================================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "emdcbackend",
]


# ============================================================================
# Middleware
# ============================================================================

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "emdcbackend.urls"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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


WSGI_APPLICATION = "emdcbackend.wsgi.application"


# ============================================================================
# Database (Postgres via env)
# ============================================================================

# In both dev and prod, we read database settings from env.
# For local dev, put these in .local.env.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

# Connection pooling - reuse connections for better performance
CONN_MAX_AGE = 60


# ============================================================================
# Password validation
# ============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "emdcbackend.auth.password_validators.UppercasePasswordValidator",
    },
    {
        "NAME": "emdcbackend.auth.password_validators.LowercasePasswordValidator",
    },
    {
        "NAME": "emdcbackend.auth.password_validators.SpecialCharacterPasswordValidator",
    },
]


# ============================================================================
# Internationalization / timezone
# ============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True


# ============================================================================
# Static files
# ============================================================================

STATIC_URL = "static/"


# ============================================================================
# Default primary key field type
# ============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ============================================================================
# CSRF failure handling
# ============================================================================

# Return JSON on CSRF failures (for Postman/browser API calls)
CSRF_FAILURE_VIEW = "emdcbackend.views.errors.csrf_failure"


# ============================================================================
# Email (Resend via env)
# ============================================================================

# In dev you can:
#   EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# in .local.env so emails just print to console.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)

# SMTP config for Resend
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.resend.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "resend")
EMAIL_HOST_PASSWORD = os.environ.get("RESEND_API_KEY")

DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    "EMDC Contest <noreply@emdcresults.com>",


)
