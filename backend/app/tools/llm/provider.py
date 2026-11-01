"""Provider abstraction over the configured generation backends.

Every LLM/vision call flows through :class:`LLMProvider` implementations so the
pipeline is provider-agnostic: the Meta Model API is the default provider and a
local OpenAI-compatible endpoint (e.g. Baseten Muse Spark Open, Ollama) is
selectable with ``LLM_PROVIDER=local``.
"""
import base64
import json
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.tools.llm.provider")


class LLMProvider:
    name = "base"
    default_model = ""

    async def generate(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        media: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
        model: Optional[str] = None,
    ) -> str:
        """Return raw completion text; ``schema`` requests structured output."""
        raise NotImplementedError

    async def transcribe(self, audio_path: str, *, language: str = "en", job_id: Optional[str] = None) -> Dict[str, Any]:
        """Return {"full_text": str, "segments": [{start, end, text, speaker}]}."""
        raise NotImplementedError


def _strip_json_fences(raw: str) -> str:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.IGNORECASE)
    return cleaned


def _extract_json_block(raw: str):
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def normalize_image_media(media: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw byte media into provider-independent base64 data URLs."""
    out = []
    for m in media or []:
        data = m.get("data")
        mime = m.get("mime_type") or "image/jpeg"
        if isinstance(data, bytes):
            out.append({"mime_type": mime, "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"})
        elif isinstance(data, str) and data.startswith("data:"):
            out.append({"mime_type": mime, "url": data})
        elif isinstance(data, str):
            out.append({"mime_type": mime, "url": f"data:{mime};base64,{data}"})
    return out


class _OpenAICompatibleProvider(LLMProvider):
    """Shared OpenAI-compatible chat-completions backend for Meta and local models."""

    name = "base"
    default_model = ""

    def __init__(self, base_url: str, api_key: str, default_model: str, timeout: int = 60, headers: Optional[Dict[str, str]] = None):
        from openai import OpenAI

        from app.config import settings
        self._settings = settings
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            default_headers=headers or {},
        )
        self._default_model = default_model

    @property
    def default_model(self) -> str:
        return self._default_model

    def _system_message(self, system: Optional[str]) -> List[Dict[str, Any]]:
        return [{"role": "system", "content": system}] if system else []

    def _user_content(self, prompt: str, media: Optional[List[Dict[str, Any]]]) -> Any:
        urls = [p for p in normalize_image_media(media or []) if p["mime_type"].startswith("image/")]
        if not urls:
            return prompt
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for u in urls:
            content.append({"type": "image_url", "image_url": {"url": u["url"]}})
        return content

    def _request_kwargs(self, schema: Optional[Dict[str, Any]], name: str) -> Dict[str, Any]:
        if not schema:
            return {}
        formatted = schema if isinstance(schema, dict) and "name" in schema and "schema" in schema else {
            "name": name, "schema": schema,
        }
        return {"response_format": {"type": "json_schema", "json_schema": formatted}}

    async def generate(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        media: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
        model: Optional[str] = None,
    ) -> str:
        import asyncio

        model_name = model or self._default_model
        last_err: Optional[Exception] = None

        def _one_request(model_id: str, *, strict_schema: bool):
            kwargs = self._request_kwargs(schema, "chronocut_plan") if strict_schema else {}
            return self._client.chat.completions.create(
                model=model_id,
                messages=self._system_message(system) + [
                    {"role": "user", "content": self._user_content(prompt, media)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        for attempt in range(3):
            for model_id in [model_name] + list(self._settings.meta_text_fallback_models):
                try:
                    if attempt == 0 and schema:
                        rd = await asyncio.to_thread(_one_request, model_id, strict_schema=True)
                    else:
                        rd = await asyncio.to_thread(
                            _one_request, model_id,
                            strict_schema=False if schema else True,
                        )
                    return rd.choices[0].message.content or ""
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    msg = str(e).lower()
                    transient = any(t in msg for t in ("429", "rate", "timeout", "503", "overloaded"))
                    logger.warning(f"{self.name} {model_id} failed (attempt {attempt}): {type(e).__name__}: {e}")
                    if not transient:
                        continue
                    await asyncio.sleep(min(2 ** attempt * 2, 30))
        raise RuntimeError(f"{self.name} request failed after retries: {last_err}")

    def structured_json(self, raw: str):
        """Best-effort JSON extraction (schema mode, fenced, or embedded block)."""
        if not raw:
            raise ValueError("empty completion")
        for candidate in (raw, _strip_json_fences(raw)):
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                pass
        block = _extract_json_block(raw)
        if block is not None:
            return block
        raise ValueError("completion contained no JSON object")

    # ---- speech-to-text ----------------------------------------------------
    async def transcribe(self, audio_path: str, *, language: str = "en", job_id: Optional[str] = None) -> Dict[str, Any]:
        import asyncio

        from app.tools.audio.meta_asr import transcribe_wav_chunked

        return await transcribe_wav_chunked(audio_path, job_id=job_id, language=language)

    # ---- video understanding -------------------------------------------------
    async def describe_video(self, video_path: str, *, prompt: str, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Return a structured video summary using the Files API when uploadable."""
        import asyncio

        from app.config import settings
        size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        summary: Dict[str, Any] = {}

        if size <= 100 * 1024 * 1024:  # cap uploads per job stage
            try:
                file_id = await asyncio.to_thread(self._upload_file, video_path)
                text = await asyncio.to_thread(
                    self._chat_video_prompt, prompt, file_id,
                )
                summary = self.structured_json(text)
                try:
                    await asyncio.to_thread(self._delete_file, file_id)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"{self.name} video understanding failed: {e}")

        if not summary:
            summary = await self._describe_video_keyframes(video_path, prompt=prompt)
        return summary

    def _upload_file(self, path: str) -> str:
        with open(path, "rb") as f:
            res = self._client.files.create(file=f, purpose="user_data")
        return res.id

    def _delete_file(self, file_id: str) -> None:
        self._client.files.delete(file_id)

    def _chat_video_prompt(self, prompt: str, file_id: str) -> str:
        rd = self._client.chat.completions.create(
            model=self._default_model,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"file_id": file_id}},
                ]},
            ],
            temperature=0.4,
            max_tokens=2048,
        )
        return rd.choices[0].message.content or ""

    async def _describe_video_keyframes(self, video_path: str, *, prompt: str) -> Dict[str, Any]:
        """Fallback: extract up to three frames and tag them as images."""
        import asyncio
        import subprocess

        frames = []
        try:
            with tempfile.TemporaryDirectory(prefix="cc_keyframes_") as d:
                for ts in ("5", "0.5", "0"):
                    out = os.path.join(d, f"frame_{ts.replace('.', '_')}.jpg")
                    res = await asyncio.to_thread(
                        subprocess.run,
                        ["ffmpeg", "-y", "-ss", ts, "-i", video_path, "-frames:v", "1", out],
                        capture_output=True, text=True, timeout=60,
                    )
                    if res.returncode == 0 and os.path.exists(out):
                        break
                for fname in sorted(os.listdir(d)):
                    if fname.endswith(".jpg"):
                        with open(os.path.join(d, fname), "rb") as f:
                            frames.append(f.read())
                    if len(frames) >= 3:
                        break
        except Exception as e:
            logger.warning(f"keyframe extraction failed: {e}")
        if not frames:
            return {}
        media = [{"data": fr, "mime_type": "image/jpeg", "name": f"frame-{i}"} for i, fr in enumerate(frames)]
        text = await self.generate(prompt=prompt, media=media, temperature=0.4, max_tokens=2048)
        try:
            return self.structured_json(text)
        except ValueError:
            return {}


class MetaProvider(_OpenAICompatibleProvider):
    """Meta Model API client (OpenAI-compatible chat completions endpoint).

    Retargeted to Muse Spark Open on Baseten: ``META_BASE_URL`` points at the
    Baseten endpoint and calls carry ``X-Baseten-Api-Key`` plus a session
    affinity header so routed requests stay on the same model instance.
    """

    name = "meta"

    def __init__(self):
        from app.config import settings
        api_key = settings.provider_api_key
        if not api_key:
            raise RuntimeError("MODEL_API_KEY/META_API_KEY is not configured.")
        _OpenAICompatibleProvider.__init__(
            self,
            base_url=settings.META_BASE_URL,
            api_key=api_key,
            default_model=settings.META_TEXT_MODEL,
            headers={
                "X-Baseten-Api-Key": api_key,
                "X-Session-Id": "chronocut-backend",
            },
        )


class LocalOpenWeightProvider(_OpenAICompatibleProvider):
    """Local OpenAI-compatible endpoint (Baseten Muse Spark Open, Ollama, etc.).

    Keyed by ``LLM_PROVIDER=local``; URL via ``LOCAL_LLM_BASE_URL``, model via
    ``LOCAL_LLM_MODEL``.
    """

    name = "local"

    def __init__(self):
        from app.config import settings
        api_key = settings.LOCAL_LLM_API_KEY or "local"
        _OpenAICompatibleProvider.__init__(
            self,
            base_url=settings.LOCAL_LLM_BASE_URL,
            api_key=api_key,
            default_model=settings.LOCAL_LLM_MODEL,
        )


def get_provider(provider_name: Optional[str] = None) -> LLMProvider:
    from app.config import settings

    name = ((provider_name or settings.LLM_PROVIDER) or "meta").strip().lower()
    if name == "local":
        return LocalOpenWeightProvider()
    return MetaProvider()
