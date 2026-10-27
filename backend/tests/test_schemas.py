from app.schemas import validate_profiles, RenderProfileSchema, JobStatusSchema


def test_validate_profiles_keeps_known_and_drops_unknown():
    out = validate_profiles(["shorts", "bogus_profile", "square"])
    assert set(out) == {"shorts", "square"}


def test_validate_profiles_falls_back_to_default():
    assert validate_profiles([]) == ["youtube_landscape"]
    assert validate_profiles(["nope"]) == ["youtube_landscape"]


def test_render_profile_schema():
    p = RenderProfileSchema(name="shorts", width=1080, height=1920, fps=30)
    assert p.width == 1080 and p.height == 1920


def test_job_status_schema_allows_extra_fields():
    j = JobStatusSchema(job_id="abc", status="COMPLETE", progress_percent=100, extra="kept")
    assert j.extra == "kept"
