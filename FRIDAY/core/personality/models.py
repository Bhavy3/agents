from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PersonaMode(StrEnum):
    ENGINEERING = "engineering"
    TEACHING = "teaching"
    CASUAL = "casual"
    STRESS = "stress"


class EmotionState(StrEnum):
    CALM = "calm"
    URGENT = "urgent"
    FRUSTRATED = "frustrated"
    CONFUSED = "confused"


@dataclass(slots=True, frozen=True)
class StyleConfig:
    tone: str
    verbosity: str  # "concise", "normal", "detailed"
    pacing: str     # "fast", "normal", "slow"
    humor_level: float = 0.0  # 0.0 to 1.0


@dataclass(slots=True)
class ConversationProfile:
    user_id: str
    preferred_mode: PersonaMode = PersonaMode.ENGINEERING
    verbosity_preference: str = "normal"
    technical_depth: float = 0.7
    likes_humor: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
