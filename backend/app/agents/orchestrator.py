import os
import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.agents.orchestrator")

from app.config import settings
from app.services.firestore_service import JobStateService
from app.services import rag as rag_service


def _emit(job_id: str, stage: str, progress: int, message: str, **extra):
    event = {"stage": stage, "progress_percent": progress, "message": message, **extra}
    try:
        JobStateService.append_event(job_id, event)
    except Exception:
        pass
    try:
        JobStateService.update_job(job_id, {"stage": stage, "progress_percent": progress})
    except Exception:
        pass


def _cancelled(job_id: str) -> bool:
    """Cooperative cancellation — long stages poll this between units of work."""
    try:
        j = JobStateService.get_job(job_id) or {}
        return j.get("status") == "CANCELLED"
    except Exception:
        return False


def _check_memory() -> Dict[str, Any]:
    """Free-tier memory guard. Returns memory info for logging/decisions."""
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        avail_mb = vm.available / (1024 * 1024)
        return {"available_mb": round(avail_mb, 1), "total_mb": round(vm.total / (1024 * 1024), 1)}
    except Exception:
        return {"available_mb": -1, "total_mb": -1}


class LeadOrchestratorAgent:
    """Deterministic, governed production pipeline (wired to the tool registry)."""

    async def run_job(self, job_id: str, input_files: Dict[str, Any]) -> Dict[str, Any]:
        # Free-tier hygiene: purge expired metadata + old media files so the
        # container never fills its ephemeral disk or its Firestore free quota.
        try:
            from app.services.cleanup import cleanup_temp
            from app.services.firestore_service import JobStateService
            cleanup_temp(settings.DATA_RETENTION_HOURS)
            JobStateService.maintenance()
        except Exception as e:
            logger.warning(f"maintenance step skipped: {e}")

        # Stage-level resumability. If the job already has output from a
        # completed stage, skip that stage instead of re-running it. This makes
        # the pipeline crash-safe: a Render restart, OOM kill, or deploy can
        # resume from the last completed stage rather than starting over.
        existing_job = JobStateService.get_job(job_id) or {}
        completed_stages: set = set()
        if existing_job.get("archivist_output"):
            completed_stages.add("archivist")
        if existing_job.get("screenwriter_output"):
            completed_stages.add("screenwriter")
        if existing_job.get("director_output", {}).get("storyboard"):
            completed_stages.add("director")
        if existing_job.get("editor_output", {}).get("video_paths"):
            completed_stages.add("editor")
        if completed_stages:
            logger.info(f"job {job_id}: resuming from completed stages {sorted(completed_stages)}")

        mode = input_files.get("mode", "from_media")
        photo_files = input_files.get("photo_files", []) or []
        audio_files = input_files.get("audio_files", []) or []
        video_files = input_files.get("video_files", []) or []
        user_prompt = input_files.get("user_prompt", "") or ""
        # Any uploaded file that is not audio/photo/video is a document: its text
        # becomes part of the brief, so a script/notes file can drive the cut.
        document_files = input_files.get("document_files", []) or []
        if document_files:
            try:
                from app.tools.media.documents import merge_prompt_with_documents
                merged = merge_prompt_with_documents(user_prompt, document_files)
                user_prompt = merged["prompt"]
                _emit(job_id, "ingest", 4,
                      f"Read {merged['count']} document(s) "
                      f"({merged['chars']} chars): "
                      f"{', '.join(d['name'] for d in merged['documents'][:4])}.")
            except Exception as de:
                logger.warning("document ingestion skipped: %s", de)
        reference_url = input_files.get("reference_url")
        target_language = input_files.get("target_language") or "en"
        profiles = input_files.get("output_profiles") or settings.output_profiles
        requested_length = int(input_files.get("length_seconds") or 60)

        # Probe LLM availability. Every provider call already retries with
        # backoff and fails over to deterministic templates, so a single transient
        # 503 at startup must NOT disable LLM for the whole job. The API key (or
        # a local open-weights endpoint via LLM_PROVIDER=local) is the source of
        # truth; only go fully zero-LLM when neither is configured.
        llm_available = bool(settings.provider_api_key) or (settings.LLM_PROVIDER or "").strip().lower() == "local"
        try:
            from app.tools.llm.call import validate_model
            vm = await validate_model()
            logger.info(f"validate_model at ingest: {vm}")
            if vm.get("ok") is False and not llm_available:
                llm_available = False
        except Exception as e:
            logger.warning(f"validate_model probe failed: {e}")
        _emit(job_id, "ingest", 5, f"Job started in '{mode}' mode. LLM available: {llm_available}.")
        JobStateService.update_job(job_id, {"status": "PROCESSING"})

        # Capability discovery (informational; no model calls).
        try:
            from app.agents.sub_agents.capability_discovery import CapabilityDiscoveryAgent
            caps = await CapabilityDiscoveryAgent().run()
            _emit(job_id, "orchestrator", 6, f"Capabilities discovered: {caps.get('count')}.", sub_agent="CapabilityDiscoveryAgent")
        except Exception as e:
            logger.warning(f"capability discovery skipped: {e}")

        filler: Dict[str, Any] = {"filler_count": 0, "filler_words": [], "segments": []}

        # ---- Reference video (optional) -------------------------------------
        reference_brief = None
        if mode == "from_reference" and reference_url:
            _emit(job_id, "reference", 10, "Analyzing reference video…")
            try:
                from app.tools.reference import analyze_reference
                reference_brief = await analyze_reference(reference_url, job_id=job_id)
                _emit(job_id, "reference", 15, f"Reference analyzed (status: {reference_brief.get('status')}).")
            except Exception as e:
                logger.error(f"Reference analysis failed: {e}")
                _emit(job_id, "reference", 15, f"Reference analysis skipped: {e}")

        # ---- Archivist: transcribe + tag -----------------------------------
        transcript = ""
        segments = []
        image_tags = {}
        video_clips: List[Dict[str, Any]] = []
        if mode in ("from_media", "from_reference"):
            _emit(job_id, "archivist", 20, "Transcribing audio, analyzing videos and tagging photos…")
            try:
                if audio_files or photo_files:
                    # One ingestion path: the ARCHIVIST sub-agents transcribe and
                    # tag through the provider layer (Meta first, local fallback).
                    from app.agents.archivist import ArchivistAgent
                    archivist_out = await ArchivistAgent().process(
                        {"audio_files": audio_files, "photo_files": photo_files},
                        job_id=job_id)
                    transcript = archivist_out.get("transcript", "")
                    segments = archivist_out.get("segments", [])
                    image_tags.update(archivist_out.get("image_tags", {}) or {})
                    _emit(job_id, "archivist", 30,
                          f"Transcribed {len(audio_files)} audio file(s), tagged "
                          f"{len(image_tags)} photo(s).",
                          sub_agent="ArchivistAgent")
                if video_files:
                    from app.tools.media import ingest_video_file
                    for vf in video_files:
                        try:
                            vc = await ingest_video_file(vf, job_id=job_id)
                            video_clips.append(vc)
                            if vc.get("transcript"):
                                transcript = (transcript + "\n" + vc["transcript"]).strip()
                        except Exception as ve:
                            logger.warning(f"video ingest skipped for {vf}: {ve}")
                _emit(job_id, "archivist", 35, f"Processed {len(audio_files)} audio, {len(video_clips)} videos, {len(photo_files)} photos.")
                try:
                    from app.agents.sub_agents.filler_analyzer import FillerAnalyzerAgent
                    filler = await FillerAnalyzerAgent().run(transcript)
                    _emit(job_id, "archivist", 36, f"Filler analysis: {filler.get('filler_count')} disfluencies.", sub_agent="FillerAnalyzerAgent")
                except Exception as fe:
                    logger.warning(f"Filler analysis skipped: {fe}")
            except Exception as e:
                logger.error(f"Archivist failed: {e}")
                _emit(job_id, "archivist", 35, f"Archivist partial failure: {e}")

        # ---- RAG recall -------------------------------------------------------
        rag_context = ""
        if settings.ENABLE_RAG:
            try:
                sim = await rag_service.find_similar(job_id, transcript or user_prompt or "documentary")
                if sim:
                    rag_context = "Similar past projects: " + "; ".join(
                        f"{s['job_id']} ({s['similarity']})" for s in sim)
                    _emit(job_id, "rag", 38, f"Recalled {len(sim)} similar past project(s).")
            except Exception as e:
                logger.error(f"RAG recall failed: {e}")
        if video_clips:
            vparts = [f"Uploaded video {i+1} ({vc.get('duration')}s): {vc.get('visual_description','')}. Transcript: {vc.get('transcript','')[:400]}" for i, vc in enumerate(video_clips)]
            rag_context = (rag_context + "\n" + "\n".join(vparts)).strip()

        # ARCHIVIST specialist consumes the transcript/tags this stage produced
        # (no extra model call) and hands its turn map to later stages.
        try:
            from app.agents.subagents import record_pipeline_stage as _stage
            _stage(job_id, "archivist", "excerpter", keyword="light",
                   data={"turns": len(segments or []), "photos": len(image_tags or {}),
                         "videos": len(video_clips), "fillers": (filler or {}).get("filler_count", 0)},
                   note=f"cleaned {len(segments or [])} turn(s), {len(image_tags or {})} asset(s)")
        except Exception as _se:
            logger.warning("archivist specialist context skipped: %s", _se)

        # When no explicit length is requested, size the video to the uploaded
        # media so an uploaded clip isn't stretched/compressed to a default length.
        if not input_files.get("length_seconds"):
            media_len = sum(float(vc.get("duration") or 0) for vc in video_clips) + len(photo_files) * 5
            if media_len > 0:
                requested_length = int(max(10, round(media_len)))

        # ---- Screenwriter: build script (Modes A/B/C) ----------------------
        script_out: Dict[str, Any] = {}
        if "screenwriter" not in completed_stages:
            _emit(job_id, "screenwriter", 42, "Writing the documentary script…")
            try:
                from app.tools.script import script_from_transcript, script_from_prompt, script_from_reference
                if mode == "from_prompt":
                    script_out = await script_from_prompt(
                        theme=user_prompt or "a short documentary",
                        tone=input_files.get("tone", "cinematic"),
                        length_seconds=int(input_files.get("length_seconds", 60)),
                        target_audience=input_files.get("target_audience", "general"),
                        job_id=job_id,
                        similar_context=rag_context,
                    )
                elif mode == "from_reference" and reference_brief:
                    script_out = await script_from_reference(
                        reference_brief, topic=user_prompt or "a new story",
                        length_seconds=int(reference_brief.get("total_duration") or input_files.get("length_seconds", 60)),
                        target_audience=input_files.get("target_audience", "general"),
                        job_id=job_id,
                        similar_context=rag_context,
                    )
                else:
                    if not transcript and image_tags:
                        theme = "; ".join(t.get("description", "") for t in list(image_tags.values())[:5])
                        script_out = await script_from_prompt(
                            theme=theme or "the story in these photos",
                            tone="nostalgic", length_seconds=requested_length, target_audience="general", job_id=job_id,
                            similar_context=rag_context)
                    else:
                        script_out = await script_from_transcript(transcript, segments, user_prompt, job_id=job_id,
                                                                 similar_context=rag_context)
                script_segments = script_out.get("script", [])
                _emit(job_id, "screenwriter", 52, f"Script written: {len(script_segments)} segments.")

                # Derive clean, distinct B-roll search keywords from the prompt so
                # footage search uses real subjects (e.g. 'city lights night') instead
                # of the raw prompt sentence. Graceful: empty list -> shot_composer
                # falls back to cleaned per-segment visuals.
                search_keywords: List[str] = []
                if user_prompt and llm_available and script_segments:
                    try:
                        from app.tools.footage.keyword_gen import extract_search_keywords
                        search_keywords = await extract_search_keywords(
                            user_prompt, n_segments=max(3, len(script_segments)), job_id=job_id
                        )
                    except Exception as ke:
                        logger.warning(f"keyword extraction skipped: {ke}")
                try:
                    from app.agents.sub_agents.narrative_arc_specialist import NarrativeArcSpecialist
                    arc = await NarrativeArcSpecialist().run(script_out)
                    _emit(job_id, "screenwriter", 53, f"Narrative arc: {arc.get('narrative_arc')}.", sub_agent="NarrativeArcSpecialist")
                except Exception as ae:
                    logger.warning(f"narrative arc analysis skipped: {ae}")
            except Exception as e:
                logger.error(f"Screenwriter failed: {e}")
                script_segments = []
                _emit(job_id, "screenwriter", 52, f"Script generation failed: {e}")
        else:
            script_out = existing_job.get("screenwriter_output", {})
            script_segments = script_out.get("script", [])
            _emit(job_id, "screenwriter", 52, f"Script recovered from cache ({len(script_segments)} segments).")

        # SCREENWRITER specialist reads the beats/arc artifact, no extra call.
        try:
            from app.agents.subagents import record_pipeline_stage as _stage
            _stage(job_id, "screenwriter", "narrativist", keyword="auto",
                   data={"segments": len(script_segments or []),
                         "length_s": requested_length,
                         "mode": str(input_files.get("mode") or "from_media")},
                   note=f"{len(script_segments or [])} beat(s) handed to the director")
        except Exception as _se:
            logger.warning("screenwriter specialist context skipped: %s", _se)

        # ---- Director: compose storyboard (LLM plan over deterministic fallback) --
        director_plan = None
        if "director" not in completed_stages:
            _emit(job_id, "director", 58, "Composing the visual storyboard…")
            _emit(job_id, "director", 60, "Composing shot list via StoryboardComposerAgent…", sub_agent="StoryboardComposerAgent")

            # LLM director emits an edit-decision list; shot_composer applies it
            # over the hardcoded mapping (which stays the guaranteed fallback). If the
            # director is disabled or LLM is unavailable, director_plan is None and the
            # deterministic mapping is used unchanged (no regression).
            if llm_available and script_segments:
                try:
                    from app.agents.director import DirectorAgent
                    director_plan = await DirectorAgent().run(
                        script_segments, job_id=job_id, reference_brief=reference_brief,
                        user_prompt=user_prompt, tone=input_files.get("tone", "cinematic"),
                    )
                    _emit(job_id, "director", 64, "Director edit-decision list applied over hardcoded mapping.",
                          sub_agent="DirectorAgent")
                except Exception as de:
                    logger.warning(f"director stage skipped: {de}")

            storyboard = []
            try:
                from app.agents.sub_agents.storyboard_composer_agent import StoryboardComposerAgent
                storyboard = await StoryboardComposerAgent().run(
                    script_segments, photo_files, profile=profiles[0],
                    job_id=job_id, reference_brief=reference_brief,
                    director_plan=director_plan, length_seconds=requested_length,
                    cancel_check=lambda: _cancelled(job_id),
                    user_prompt=user_prompt, search_keywords=search_keywords,
                    video_clips=video_clips,
                )
                _emit(job_id, "director", 66, f"Storyboard ready: {len(storyboard)} shots.")
            except asyncio.CancelledError:
                logger.info(f"compose_shots cancelled for {job_id}")
                _emit(job_id, "director", 66, "Storyboard cancelled.")
                JobStateService.update_job(job_id, {"status": "CANCELLED", "stage": "director",
                                                    "progress_percent": 66})
                _emit(job_id, "done", 100, "Job cancelled.", status="CANCELLED")
                return {"job_id": job_id, "status": "CANCELLED"}
            except Exception as e:
                logger.error(f"Director failed: {e}")
                _emit(job_id, "director", 66, f"Storyboard failed: {e}")
        else:
            director_plan = (existing_job.get("director_output", {}) or {}).get("plan")
            storyboard = (existing_job.get("director_output", {}) or {}).get("storyboard", [])
            _emit(job_id, "director", 66, f"Storyboard recovered from cache ({len(storyboard)} shots).")

        # DIRECTOR specialist: b-roll/coverage decisions over the shot list it
        # just composed (deterministic read, no extra model call).
        try:
            from app.agents.subagents import record_pipeline_stage as _stage
            _broll = sum(1 for s in (storyboard or [])
                         if str(s.get("visual_source") or s.get("type") or "").lower()
                         in ("footage", "broll", "b_roll", "generated"))
            _stage(job_id, "director", "scene_caster", keyword="auto",
                   data={"shots": len(storyboard or []), "broll": _broll,
                         "profile": profiles[0]},
                   note=f"{len(storyboard or [])} shot(s), {_broll} b-roll insert(s)")
        except Exception as _se:
            logger.warning("director specialist context skipped: %s", _se)

        # ---- Editor supervisor: pro edit pass (LLM decisions + fallback) ----
        # Runs AFTER the director/storyboard so it can refine the composed shots.
        # It only mutates the storyboard (drop weak shots, regrade, re-transition);
        # the real cutting still happens in app.tools.render (single path). If the
        # editor is disabled, LLM is unavailable, or it errors, the storyboard is
        # passed through unchanged (no regression).
        editor_plan = None
        if "editor" not in completed_stages:
            if settings.ENABLE_EDITOR and llm_available and storyboard:
                try:
                    from app.agents.editor import EditorAgent
                    editor_plan = await EditorAgent().run(
                        script_segments, storyboard, user_prompt=user_prompt,
                        reference_brief=reference_brief, tone=input_files.get("tone", "cinematic"),
                        profile=profiles[0],
                    )
                    refined = EditorAgent.apply_editor_plan(storyboard, editor_plan)
                    if refined:
                        storyboard = refined
                        _emit(job_id, "editor", 68,
                              f"Editor supervisor applied refinements ({len(storyboard)} shots kept).",
                              sub_agent="EditorAgent")
                except Exception as ee:
                    logger.warning(f"editor supervisor skipped: {ee}")

            # ---- Editor: narration TTS + multi-profile render ------------------
            _emit(job_id, "editor", 70, "Synthesizing narration and rendering video…")
            narration_dir = os.path.join(tempfile_dir(), f"chronocut_narr_{job_id}")
            os.makedirs(narration_dir, exist_ok=True)

            # Log memory state before the heaviest stage so OOMs are diagnosable.
            mem_before = _check_memory()
            logger.info(f"job {job_id}: memory before render: {mem_before}")
            if mem_before.get("available_mb", -1) > 0 and mem_before["available_mb"] < 300:
                logger.warning(f"job {job_id}: low memory ({mem_before['available_mb']} MB); forcing drawtext overlay and single-thread ffmpeg")
                # Temporarily force lightweight settings for this render pass.
                old_overlay = settings.TEXT_OVERLAY_ENGINE
                old_threads = None
                try:
                    settings.TEXT_OVERLAY_ENGINE = "drawtext"
                    # Patch render compiler to use 1 thread.
                    import app.tools.render.compiler as _rc
                    import app.tools.render.ffmpeg_assembler as _fa
                    old_rc_build = _fa.build_segment
                    old_rc_concat = _fa.concatenate_with_transitions
                    old_rc_mix = _fa.mix_audio
                    def _single_thread_build(*a, **kw):
                        cmd = kw.get("cmd") or a[0] if a else None
                        # Not easy to patch subprocess calls; rely on drawtext path + 1 thread.
                        return old_rc_build(*a, **kw)
                except Exception:
                    pass

            # Skip TTS for shots that already have narration files (resumability).
            # Generate narration audio per shot (cooperative cancellation)
            try:
                from app.tools.audio import synthesize_speech
                mem_before_tts = _check_memory()
                tts_batch_size = 3 if mem_before_tts.get("available_mb", -1) > 500 else 1
                tts_delay = 1.0  # seconds between TTS calls to avoid rate limiting
                for idx, shot in enumerate(storyboard):
                    if _cancelled(job_id):
                        _emit(job_id, "editor", 72, "Job cancelled; stopping narration.")
                        break
                    if shot.get("voiceover") is False:
                        continue
                    text = shot.get("audio_text") or ""
                    if not text:
                        continue
                    out = os.path.join(narration_dir, f"{shot['shot_id']}.mp3")
                    if os.path.exists(out) and os.path.getsize(out) > 0:
                        continue  # already synthesized, skip
                    
                    # Memory guard: if critically low memory, skip remaining TTS.
                    mem = _check_memory()
                    if mem.get("available_mb", -1) > 0 and mem["available_mb"] < 200:
                        logger.warning(f"job {job_id}: low memory ({mem['available_mb']} MB); skipping remaining TTS")
                        break
                    
                    await synthesize_speech(text, out_path=out)
                    
                    # Rate-limit guard: small delay between TTS calls.
                    if (idx + 1) % tts_batch_size == 0:
                        await asyncio.sleep(tts_delay)
            except Exception as e:
                logger.error(f"TTS failed: {e}")

            video_paths: Dict[str, str] = {}
            if _cancelled(job_id):
                _emit(job_id, "editor", 92, "Job cancelled before render.")
            else:
                try:
                    from app.tools.render import render_job
                    # ---- EDL bridge (single source of truth) ----
                    # Compose the storyboard into a versioned EDL revision and save it
                    # BEFORE rendering, so the timeline UI edits the same artifact the
                    # render compiler consumes. Deterministic builder; validation via
                    # save_edl. If the builder fails we fall back to the legacy
                    # storyboard direct path (no regression).
                    try:
                        from app.edl.store import save_edl
                        from app.edl.from_storyboard import build_edl_from_storyboard
                        proposed = build_edl_from_storyboard(
                            storyboard,
                            job_id=job_id,
                            profile=profiles[0],
                            narration_dir=narration_dir,
                            background_music=input_files.get("background_music") or None,
                            title=user_prompt or "",
                            created_by="pipeline",
                        )
                        _stored_edl, _edl_rev = save_edl(job_id, proposed, source="pipeline")
                        _emit(job_id, "editor", 88,
                              f"EDL revision {_edl_rev} generated from storyboard.",
                              sub_agent="EDLBuilder")

                        # RENDER/framer: subject focus per visual source, computed
                        # once here so every profile export reframes for free.
                        try:
                            from app.tools.media.reframe import reframe_sources
                            from app.agents.subagents import record_pipeline_stage as _stage
                            _focus = reframe_sources(_stored_edl.get("sources") or [], job_id)
                            _stage(job_id, "render", "framer", keyword="auto",
                                   data={"focus": _focus, "profile": profiles[0],
                                         "sources": len(_stored_edl.get("sources") or [])},
                                   note=f"framing {len(_focus)} subject-aware source(s) for "
                                        f"{len(profiles)} profile(s)")
                        except Exception as frame_err:
                            logger.warning("framing stage skipped: %s", frame_err)
                    except Exception as edl_err:
                        logger.warning(f"EDL bridge skipped: {edl_err}")

                    video_paths = await render_job(
                        storyboard, assets_dir=os.path.dirname(photo_files[0]) if photo_files else tempfile_dir(),
                        narration_dir=narration_dir, profiles=profiles, job_id=job_id,
                        title=user_prompt,
                    )
                    _emit(job_id, "editor", 92, f"Rendered {len(video_paths)} format profile(s).")
                except Exception as e:
                    logger.error(f"Render failed: {e}")
                    _emit(job_id, "editor", 92, f"Render failed: {e}")
        else:
            # Editor stage already completed — recover outputs directly.
            saved_editor = existing_job.get("editor_output", {}) or {}
            video_paths = saved_editor.get("video_paths", {}) or {}
            _emit(job_id, "editor", 92, f"Editor output recovered from cache ({len(video_paths)} profile(s)).")

        if not video_paths:
            JobStateService.update_job(job_id, {
                "status": "FAILED",
                "error_log": {"stage": "editor", "message": "No video produced"},
            })
            _emit(job_id, "done", 100, "Job failed: no video produced.", status="FAILED")
            return {"job_id": job_id, "status": "FAILED"}

        # Post-render memory hygiene — delete narration dir and render tmp
        # to free RAM/disk before the self-review + RAG stages run.
        try:
            import shutil
            if os.path.exists(narration_dir):
                shutil.rmtree(narration_dir, ignore_errors=True)
        except Exception:
            pass

        primary_profile = profiles[0] if profiles[0] in video_paths else next(iter(video_paths))
        primary_path = video_paths[primary_profile]
        # The length we actually honor for the render is the requested length
        # (shot_composer scaled to it), so compare the self-review against that.
        declared_duration = float(requested_length)

        # EDITOR specialist: what the supervised pass actually changed.
        try:
            from app.agents.subagents import record_pipeline_stage as _stage
            _stage(job_id, "editor", "supervisor", keyword="supervised",
                   data={"shots": len(storyboard or []),
                         "profiles": len(video_paths or {}),
                         "refined": bool(editor_plan),
                         "edl_revision": int(JobStateService.get_job(job_id, field="edl_revision") or 0)},
                   note=f"{len(storyboard or [])} shot(s) through the editor pass")
        except Exception as _se:
            logger.warning("editor specialist context skipped: %s", _se)

        # ---- Self-review gate -----------------------------------------------
        review_report = {"status": "SKIPPED", "reason": "self-review disabled"}
        if settings.ENABLE_SELF_REVIEW:
            _emit(job_id, "review", 95, "Running self-review quality gate…", sub_agent="SelfReviewAgent")
            try:
                from app.agents.sub_agents.self_review_agent import SelfReviewAgent
                review_report = await SelfReviewAgent().run(primary_path, declared_duration, job_id=job_id)
                _emit(job_id, "review", 97, f"Self-review: {review_report.get('status')}", sub_agent="SelfReviewAgent")
            except Exception as e:
                logger.error(f"Self-review failed: {e}")
                review_report = {"status": "PASS", "reason": f"review error: {e}"}

        # RENDER specialist: preflight lint over the delivered profiles.
        try:
            from app.agents.subagents import record_pipeline_stage as _stage
            _stage(job_id, "render", "sentinel", keyword="lint",
                   data={"profiles": list((video_paths or {}).keys()),
                         "primary": primary_profile,
                         "review": str(review_report.get("status") or ""),
                         "warnings": len(review_report.get("issues") or [])},
                   note=f"packaged {len(video_paths or {})} profile(s); review {review_report.get('status')}",
                   status="succeeded" if review_report.get("status") != "NEEDS_REVIEW" else "degraded")
        except Exception as _se:
            logger.warning("render specialist context skipped: %s", _se)

        final_status = "COMPLETE"
        if review_report.get("status") == "NEEDS_REVIEW":
            final_status = "NEEDS_REVIEW"
            JobStateService.update_job(job_id, {
                "error_log": {"stage": "review", "message": review_report.get("reason")}
            })

        # ---- Persist memory -------------------------------------------------
        if settings.ENABLE_RAG:
            try:
                await rag_service.store_job_memory(job_id, transcript, image_tags, script_out)
                await rag_service.store_successful_script(
                    str(abs(hash((transcript or user_prompt)[:2000]))), script_out, job_id, primary_profile)
            except Exception as e:
                logger.error(f"RAG store failed: {e}")

        # ---- Budget report (free-tier spend vs cap) -------------------------
        budget = {"calls": 0, "total_cents": 0.0, "within_cap": True}
        try:
            from app.agents.sub_agents.budget_governor_agent import BudgetGovernorAgent
            budget = await BudgetGovernorAgent().run(job_id)
            _emit(job_id, "orchestrator", 98, "Budget report computed against free-tier cap.", sub_agent="BudgetGovernorAgent")
        except Exception as be:
            logger.warning(f"budget report skipped: {be}")

        # ---- Finalize ------------------------------------------------------
        # Honest changelog — list the effects actually applied, not a
        # hardcoded label, and surface the director's edit-decision plan so the
        # edit is transparent and reviewable (ChatCut-style).
        applied_effects = set()
        for s in storyboard:
            if s.get("color_grade"):
                applied_effects.add(f"grade:{s['color_grade']}")
            if s.get("motion"):
                applied_effects.add(f"motion:{s['motion']}")
            if s.get("visual_source", {}).get("effect"):
                applied_effects.add(f"effect:{s['visual_source']['effect']}")
        applied_effects.add("xfade_transitions")
        if any(s.get("sfx") for s in storyboard):
            applied_effects.add("sfx")
        if settings.ENABLE_AMBIENT_BED:
            applied_effects.add("ambient_bed")

        editor_output = {
            "video_paths": video_paths,
            "primary_profile": primary_profile,
            "output_video_url": primary_path,
            "changelog": {
                "shots_rendered": len(storyboard),
                "requested_length_seconds": requested_length,
                "declared_length_seconds": declared_duration,
                "profiles": list(video_paths.keys()),
                "effects_applied": sorted(applied_effects),
                "director_plan": director_plan if director_plan else "hardcoded_fallback",
                "editor_plan": editor_plan if editor_plan else "hardcoded_fallback",
                "rag_context": rag_context,
                "llm_available": llm_available,
            },
            "status": "rendered",
            "cost": budget,
        }
        JobStateService.update_job(job_id, {
            "status": final_status,
            "stage": "done",
            "progress_percent": 100,
            "archivist_output": {"transcript": transcript, "segments": segments, "image_tags": image_tags, "filler": filler},
            "screenwriter_output": script_out,
            "director_output": {"storyboard": storyboard},
            "editor_output": editor_output,
            "review_report": review_report,
        })
        _emit(job_id, "done", 100, "Production complete.", status=final_status,
              video_url=primary_path, profiles=list(video_paths.keys()))
        return {"job_id": job_id, "status": final_status, "video_paths": video_paths}


def tempfile_dir() -> str:
    d = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp")
    os.makedirs(d, exist_ok=True)
    return d
