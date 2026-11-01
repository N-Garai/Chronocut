import os
import tempfile

# Use an isolated local store for all tests (no Firestore / no media on disk).
os.environ.setdefault(
    "CHRONOCUT_LOCAL_STORE",
    os.path.join(tempfile.gettempdir(), "chronocut_test_store.json"),
)
os.environ["FIRESTORE_PROJECT_ID"] = ""
os.environ["GOOGLE_CLOUD_PROJECT"] = ""
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ""
os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = ""

# Never let a developer's local .env reach a real model provider from tests.
# Individual tests that need "a key is configured" patch settings themselves.
os.environ["CHRONOCUT_TEST"] = "1"
for _key_var in ("MODEL_API_KEY", "META_API_KEY",
                 "PEXELS_API_KEY", "PIXABAY_API_KEY", "CF_API_TOKEN", "GH_DISPATCH_TOKEN"):
    os.environ[_key_var] = ""

from app.config import settings as _app_settings

_app_settings.FIRESTORE_PROJECT_ID = None
_app_settings.GOOGLE_CLOUD_PROJECT = None
_app_settings.GOOGLE_APPLICATION_CREDENTIALS = None
_app_settings.MODEL_API_KEY = None
_app_settings.META_API_KEY = None

import app.services.firestore_service as _firestore_service

_firestore_service.get_firestore_client = lambda: None
