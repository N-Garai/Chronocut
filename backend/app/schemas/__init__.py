"""Domain schemas.

Lightweight pydantic models that document the API contract and validate
inputs. Kept minimal and free-tier safe — no extra storage or processing.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class RenderProfileSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    width: int
    height: int
    fps: int
    codec: str = "libx264"
    bitrate: str = "5M"


class ReviewReportSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    review_status: Optional[str] = None
    checks: List[Dict[str, Any]] = []
    reason: Optional[str] = None


class JobStatusSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    status: str
    stage: Optional[str] = None
    progress_percent: int = 0


def validate_profiles(names: List[str]) -> List[str]:
    """Return only known render-profile names; fall back to the default."""
    from app.tools.render.profiles import PROFILES
    valid = [n for n in (names or []) if n in PROFILES]
    return valid or ["youtube_landscape"]
