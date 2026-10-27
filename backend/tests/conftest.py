import os
import tempfile

# Use an isolated local store for all tests (no Firestore / no media on disk).
os.environ.setdefault(
    "CHRONOCUT_LOCAL_STORE",
    os.path.join(tempfile.gettempdir(), "chronocut_test_store.json"),
)
