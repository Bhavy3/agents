import json
import os
from typing import Optional
from .models import ConversationProfile, PersonaMode


class ProfileManager:
    """Manages persistent conversational preferences and user profiles."""

    def __init__(self, storage_path: str = "data/personality/profiles.json"):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        self._profiles: dict[str, ConversationProfile] = self._load()

    def _load(self) -> dict[str, ConversationProfile]:
        if not os.path.exists(self.storage_path):
            return {}
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
                return {
                    k: ConversationProfile(
                        user_id=v["user_id"],
                        preferred_mode=PersonaMode(v["preferred_mode"]),
                        verbosity_preference=v["verbosity_preference"],
                        technical_depth=v["technical_depth"],
                        likes_humor=v["likes_humor"],
                        metadata=v.get("metadata", {})
                    ) for k, v in data.items()
                }
        except Exception:
            return {}

    def save(self):
        data = {
            k: {
                "user_id": v.user_id,
                "preferred_mode": v.preferred_mode.value,
                "verbosity_preference": v.verbosity_preference,
                "technical_depth": v.technical_depth,
                "likes_humor": v.likes_humor,
                "metadata": v.metadata
            } for k, v in self._profiles.items()
        }
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def get_profile(self, user_id: str) -> ConversationProfile:
        if user_id not in self._profiles:
            self._profiles[user_id] = ConversationProfile(user_id=user_id)
        return self._profiles[user_id]

    def update_preference(self, user_id: str, key: str, value: any):
        profile = self.get_profile(user_id)
        if hasattr(profile, key):
            setattr(profile, key, value)
            self.save()
