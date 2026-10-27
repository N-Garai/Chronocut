import os
import json
import logging
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.services.firestore")


def _parse_expire(v):
    """Coerce a stored ``_expire_at`` (datetime or ISO string) to a datetime."""
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


from app.config import settings

try:
    from google.cloud import firestore  # type: ignore
    _HAVE_FIRESTORE = True
except Exception:  # pragma: no cover
    firestore = None
    _HAVE_FIRESTORE = False


_LOCAL_STORE_PATH = os.getenv("CHRONOCUT_LOCAL_STORE", "/tmp/chronocut_store.json")
_local_lock = threading.Lock()
_local_data: Dict[str, Any] = {
    "jobs": {},
    "events": {},
    "ledger": {},
    "corpus": {},
    "assets": {},
}


def _load_local() -> None:
    global _local_data
    try:
        if os.path.exists(_LOCAL_STORE_PATH):
            with open(_LOCAL_STORE_PATH, "r", encoding="utf-8") as f:
                _local_data.update(json.load(f))
    except Exception:
        pass


def _save_local() -> None:
    try:
        os.makedirs(os.path.dirname(_LOCAL_STORE_PATH), exist_ok=True)
        with open(_LOCAL_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(_local_data, f, default=str)
    except Exception as e:  # pragma: no cover
        logger.warning(f"local store save failed: {e}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


_fs_client = None
_fs_tried = False


def get_firestore_client():
    global _fs_client, _fs_tried
    if not _HAVE_FIRESTORE:
        logger.warning("Firestore unavailable: google-cloud-firestore not installed.")
        return None
    if _fs_tried:
        return _fs_client
    _fs_tried = True
    try:
        project = settings.FIRESTORE_PROJECT_ID or settings.GOOGLE_CLOUD_PROJECT
        sa_path = settings.GOOGLE_APPLICATION_CREDENTIALS
        sa_project = None
        sa_exists = False

        # R4a: inline JSON via env var takes HIGHEST precedence. This is the
        # Render-safe path: no secret file mount needed. The user pastes the
        # full service account JSON into the GOOGLE_APPLICATION_CREDENTIALS_JSON
        # environment variable (e.g. a Render "Environment Variable" secret).
        inline_json = (settings.GOOGLE_APPLICATION_CREDENTIALS_JSON or "").strip()
        if inline_json:
            try:
                import tempfile as _tmp
                fd, _sa_path = _tmp.mkstemp(suffix=".json", prefix="chronocut_sa_")
                with os.fdopen(fd, "w", encoding="utf-8") as _f:
                    _f.write(inline_json)
                sa_path = _sa_path
                sa_exists = True
                try:
                    sa_project = json.loads(inline_json).get("project_id")
                except Exception as e:
                    logger.warning(f"inline service account JSON parse failed: {e}")
                    sa_project = None
                logger.info(f"Firestore: inline SA JSON loaded (project={sa_project}).")
            except Exception as e:
                logger.warning(f"inline service account JSON write failed: {e}")
                sa_path = None
                sa_exists = False

        # R4b: if no inline JSON, try secret file locations. Render mounts secret
        # files at /etc/secrets/<name> (name = the secret's file name). The value
        # you put in GOOGLE_APPLICATION_CREDENTIALS is often a RELATIVE path like
        # "./service_account.json", which won't resolve from the working dir, so
        # we also probe the same basename under the Render secret mounts.
        if not sa_exists:
            possible_paths = []
            if sa_path:
                possible_paths.append(sa_path)
                _base = os.path.basename(sa_path)
                if _base and _base != sa_path:
                    possible_paths.extend([
                        f"/etc/secrets/{_base}",
                        f"/run/secrets/{_base}",
                    ])
            possible_paths.extend([
                "./service_account.json",
                "/etc/secrets/service_account.json",
                "/run/secrets/service_account.json",
            ])
            for path in possible_paths:
                if path and os.path.exists(path):
                    sa_path = path
                    sa_exists = True
                    try:
                        with open(sa_path, "r", encoding="utf-8") as _f:
                            sa_project = json.load(_f).get("project_id")
                    except Exception as e:
                        logger.warning(f"service account JSON parse failed at {path}: {e}")
                        sa_project = None
                    break
            if not sa_exists and sa_path:
                logger.warning(
                    f"service account file not found at any of: {possible_paths}. "
                    "On Render: set GOOGLE_APPLICATION_CREDENTIALS_JSON (env var) with the "
                    "full SA JSON, or mount a Secret File named 'service_account.json'. "
                    "Falling back to default credentials."
                )

        effective_project = project or sa_project
        if not effective_project:
            logger.warning("Firestore init skipped: no project_id configured "
                           "(set FIRESTORE_PROJECT_ID or include project_id in the SA JSON).")
            return None

        # Try service account auth first if file exists.
        if sa_exists and sa_path and os.path.exists(sa_path):
            try:
                _fs_client = firestore.Client.from_service_account_json(sa_path)
                logger.info(f"Firestore client ready (service-account, project={effective_project}).")
            except Exception as e:
                logger.warning(f"Firestore service account auth failed: {e}. "
                               "Falling back to default credentials.")
                _fs_client = None

        # Fall back to default credentials. If GOOGLE_APPLICATION_CREDENTIALS is
        # set but points to a missing file, the google-cloud library fails even
        # when we ask for default credentials; unset it temporarily so the library
        # can discover credentials via the metadata server / ADC.
        if _fs_client is None:
            old_creds = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            try:
                _fs_client = firestore.Client(project=effective_project)
                logger.info(f"Firestore client ready (default credentials, project={effective_project}).")
            except Exception as e:
                logger.warning(f"Firestore default auth failed: {e}")
                _fs_client = None
            finally:
                if old_creds is not None:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = old_creds
    except Exception as e:  # pragma: no cover
        logger.warning(f"Firestore client init failed: {e}")
        _fs_client = None
    if _fs_client is None:
        logger.warning("Firestore unavailable — using local JSON store fallback "
                       "(jobs/events/ledger persist in /tmp, NOT durable across restarts).")
    return _fs_client


class JobStateService:
    """Job/event/ledger/corpus state with an optional Firestore backend.

    When no Firestore project is configured the service transparently falls
    back to a thread-safe JSON file at ``/tmp/chronocut_store.json`` so the app
    runs fully on the free tier with zero external dependencies.
    """

    COLLECTION = "jobs"

    @classmethod
    def using_firestore(cls) -> bool:
        return get_firestore_client() is not None

    # ---- low-level doc helpers -------------------------------------------
    @classmethod
    def _put_doc(cls, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                _local_data.setdefault(collection, {})[doc_id] = data
                _save_local()
            return
        try:
            client.collection(collection).document(doc_id).set(data)
        except Exception as e:  # pragma: no cover
            logger.error(f"_put_doc failed: {e}")

    @classmethod
    def _patch_doc(cls, collection: str, doc_id: str, updates: Dict[str, Any]) -> None:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                d = _local_data.setdefault(collection, {}).setdefault(doc_id, {})
                d.update(updates)
                _save_local()
            return
        try:
            updates = _sanitize_firestore_value(dict(updates))
            client.collection(collection).document(doc_id).set(updates, merge=True)
        except Exception as e:  # pragma: no cover
            logger.error(f"_patch_doc failed: {e}")

    @classmethod
    def _get_doc(cls, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                return _local_data.get(collection, {}).get(doc_id)
        try:
            snap = client.collection(collection).document(doc_id).get()
            return snap.to_dict() if snap.exists else None
        except Exception as e:  # pragma: no cover
            logger.error(f"_get_doc failed: {e}")
            return None

    @classmethod
    def _list_collection(cls, collection: str, limit: int = 20) -> List[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                items = list(_local_data.get(collection, {}).values())
            return items[-limit:][::-1]
        try:  # pragma: no cover
            docs = client.collection(collection).order_by("created_at").limit(limit).stream()
            return [d.to_dict() for d in docs]
        except Exception as e:  # pragma: no cover
            logger.error(f"_list_collection failed: {e}")
            return []

    # ---- jobs -------------------------------------------------------------
    @classmethod
    def create_job(cls, job_id: str, user_id: str, input_files: Dict[str, Any]) -> Dict[str, Any]:
        data = {
            "job_id": job_id,
            "user_id": user_id,
            "status": "QUEUED",
            "stage": "ingest",
            "progress_percent": 0,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "_expire_at": datetime.now(timezone.utc) + timedelta(hours=settings.DATA_RETENTION_HOURS),
            "input_files": input_files,
            "mode": input_files.get("mode", "from_media"),
            "reference_url": input_files.get("reference_url"),
            "output_profiles": input_files.get("output_profiles", ["youtube_landscape"]),
            "archivist_output": {},
            "screenwriter_output": {},
            "director_output": {},
            "editor_output": {},
            "review_report": {},
            "cost_cents": 0.0,
            "error_log": {},
        }
        cls._put_doc(cls.COLLECTION, job_id, data)
        return data

    @classmethod
    def update_job(cls, job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates = dict(updates)
        updates["updated_at"] = datetime.now(timezone.utc)
        cls._patch_doc(cls.COLLECTION, job_id, updates)
        return cls.get_job(job_id)

    @classmethod
    def get_job(cls, job_id: str) -> Optional[Dict[str, Any]]:
        return cls._get_doc(cls.COLLECTION, job_id)

    @classmethod
    def list_jobs(cls, limit: int = 20) -> List[Dict[str, Any]]:
        return cls._list_collection(cls.COLLECTION, limit=limit)

    @classmethod
    def delete_job(cls, job_id: str) -> None:
        cls.update_job(job_id, {"status": "DELETED"})

    # ---- SSE events sub-collection ---------------------------------------
    @classmethod
    def append_event(cls, job_id: str, event: Dict[str, Any]) -> None:
        client = get_firestore_client()
        event = dict(event)
        event["ts"] = datetime.now(timezone.utc).isoformat()
        if client is None:
            with _local_lock:
                _load_local()
                col = _local_data.setdefault("events", {}).setdefault(job_id, [])
                event["seq"] = len(col)
                col.append(event)
                _save_local()
            return
        try:  # pragma: no cover
            parent = client.collection(cls.COLLECTION).document(job_id).collection("events")
            try:
                cnt = sum(1 for _ in parent.stream())
            except Exception:
                cnt = 0
            event["seq"] = cnt
            parent.document().set(event)
        except Exception as e:
            logger.error(f"append_event failed: {e}")

    @classmethod
    def get_events(cls, job_id: str, after_seq: int = -1) -> List[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                col = _local_data.get("events", {}).get(job_id, [])
                return [e for e in col if e.get("seq", 0) > after_seq]
        try:  # pragma: no cover
            docs = (client.collection(cls.COLLECTION).document(job_id)
                    .collection("events").order_by("seq").stream())
            return [d.to_dict() for d in docs if d.to_dict().get("seq", 0) > after_seq]
        except Exception as e:
            logger.error(f"get_events failed: {e}")
            return []

    # ---- cost ledger ------------------------------------------------------
    @classmethod
    def ledger_write(cls, job_id: str, call: Dict[str, Any]) -> None:
        call = dict(call)
        call["timestamp"] = datetime.now(timezone.utc)
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                col = _local_data.setdefault("ledger", {}).setdefault(job_id, [])
                col.append(call)
                _save_local()
            return
        try:  # pragma: no cover
            client.collection("ledger").document(job_id).collection("calls").document().set(call)
        except Exception as e:
            logger.error(f"ledger_write failed: {e}")

    @classmethod
    def get_ledger(cls, job_id: str) -> List[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                return _local_data.get("ledger", {}).get(job_id, [])
        try:  # pragma: no cover
            docs = (client.collection("ledger").document(job_id)
                    .collection("calls").order_by("timestamp").stream())
            return [d.to_dict() for d in docs]
        except Exception as e:
            logger.error(f"get_ledger failed: {e}")
            return []

    @classmethod
    def add_cost(cls, job_id: str, amount: float) -> None:
        """Atomically increment the job's cost_cents accumulator."""
        if not job_id:
            return
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                job = _local_data.setdefault("jobs", {}).setdefault(job_id, {})
                job["cost_cents"] = float(job.get("cost_cents", 0.0)) + amount
                _save_local()
            return
        try:  # pragma: no cover
            doc_ref = client.collection(cls.COLLECTION).document(job_id)
            doc_ref.update({"cost_cents": firestore.Increment(amount)})
        except Exception as e:
            logger.error(f"add_cost failed: {e}")

    # ---- corpus (RAG memory + semantic footage corpus cache) --------------
    # Capped sizes keep the store small on the free tier. Only lightweight
    # metadata + small embeddings are ever written (never raw media bytes).
    CORPUS_CAPS = {
        "memory": 50,
        "scripts": 100,
        "footage_cache": 300,
        "llm_cache": 500,
        "assets": 2000,
    }

    @classmethod
    def corpus_set(cls, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        data = dict(data)
        data["_doc_id"] = doc_id
        data["_expire_at"] = datetime.now(timezone.utc) + timedelta(hours=settings.CORPUS_RETENTION_HOURS)
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                store = _local_data.setdefault("corpus", {}).setdefault(collection, {})
                store[doc_id] = data
                cap = cls.CORPUS_CAPS.get(collection)
                if cap and len(store) > cap:
                    # Drop the oldest entries (by _expire_at) to stay bounded.
                    ordered = sorted(store.items(), key=lambda kv: _parse_expire(kv[1].get("_expire_at")) or datetime.min.replace(tzinfo=timezone.utc))
                    for k, _ in ordered[: len(store) - cap]:
                        store.pop(k, None)
                _save_local()
            return
        try:  # pragma: no cover
            client.collection("corpus").document(collection).collection("docs").document(doc_id).set(data)
        except Exception as e:
            logger.error(f"corpus_set failed: {e}")

    @classmethod
    def maintenance(cls) -> None:
        """Free-tier hygiene: purge expired local metadata and bound corpus size.

        For the Firestore backend, retention is handled server-side by a TTL
        policy on the ``_expire_at`` field (configure once in the console);
        this method only prunes the local JSON fallback store.
        """
        if get_firestore_client() is not None:
            return
        with _local_lock:
            _load_local()
            now = datetime.now(timezone.utc)

            for coll in ("jobs", "events", "ledger"):
                d = _local_data.get(coll)
                if not isinstance(d, dict):
                    continue
                expired = [k for k, v in d.items()
                           if isinstance(v, dict) and (_parse_expire(v.get("_expire_at")) or datetime.max.replace(tzinfo=timezone.utc)) < now]
                for k in expired:
                    d.pop(k, None)
            for coll, cap in cls.CORPUS_CAPS.items():
                store = _local_data.get("corpus", {}).get(coll)
                if not isinstance(store, dict) or len(store) <= cap:
                    continue
                ordered = sorted(store.items(), key=lambda kv: kv[1].get("_expire_at") or datetime.min.replace(tzinfo=timezone.utc))
                for k, _ in ordered[: len(store) - cap]:
                    store.pop(k, None)
            _save_local()

    @classmethod
    def corpus_get(cls, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                return _local_data.get("corpus", {}).get(collection, {}).get(doc_id)
        try:  # pragma: no cover
            snap = (client.collection("corpus").document(collection).collection("docs")
                    .document(doc_id).get())
            return snap.to_dict() if snap.exists else None
        except Exception as e:
            logger.error(f"corpus_get failed: {e}")
            return None

    @classmethod
    def corpus_query(cls, collection: str, field: str, op: str, value: Any,
                     limit: int = 20) -> List[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                items = list(_local_data.get("corpus", {}).get(collection, {}).values())
                if op == "==":
                    items = [i for i in items if i.get(field) == value]
                return items[:limit]
        try:  # pragma: no cover
            docs = (client.collection("corpus").document(collection).collection("docs")
                    .where(field, op, value).limit(limit).stream())
            return [d.to_dict() for d in docs]
        except Exception as e:
            logger.error(f"corpus_query failed: {e}")
            return []

    @classmethod
    def corpus_list(cls, collection: str, limit: int = 200) -> List[Dict[str, Any]]:
        client = get_firestore_client()
        if client is None:
            with _local_lock:
                _load_local()
                return list(_local_data.get("corpus", {}).get(collection, {}).values())[:limit]
        try:  # pragma: no cover
            docs = (client.collection("corpus").document(collection).collection("docs")
                    .limit(limit).stream())
            return [d.to_dict() for d in docs]
        except Exception as e:
            logger.error(f"corpus_list failed: {e}")
            return []

    # ---- asset cache (SHA256-keyed dedup) --------------------------------
    @classmethod
    def asset_cache_put(cls, sha: str, data: Dict[str, Any]) -> None:
        cls.corpus_set("assets", sha, data)

    @classmethod
    def asset_cache_get(cls, sha: str) -> Optional[Dict[str, Any]]:
        return cls.corpus_get("assets", sha)


# ---- standalone helper (module-level; resolves as a bare name
# from any call site including inside class methods) ---------------
def _sanitize_firestore_value(v: Any) -> Any:
    """Drop dict keys that are not non-empty strings and normalize
    sets/tuples so Firestore never raises 'components is not a string'."""
    if isinstance(v, dict):
        out: Dict[str, Any] = {}
        for k, val in v.items():
            if not isinstance(k, str) or k == "":
                continue
            out[k] = _sanitize_firestore_value(val)
        return out
    if isinstance(v, (set, tuple)):
        return [_sanitize_firestore_value(x) for x in v]
    if isinstance(v, list):
        return [_sanitize_firestore_value(x) for x in v]
    return v
