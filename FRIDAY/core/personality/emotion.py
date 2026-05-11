import re
from .models import EmotionState


class EmotionClassifier:
    """Classifies user emotion from text and interaction patterns."""

    def __init__(self):
        self._patterns = {
            EmotionState.FRUSTRATED: [
                re.compile(r"\b(stupid|dumb|wrong|ugh|damn|not working|fix this|waste)\b", re.IGNORECASE),
                re.compile(r"!!+$"), # Excessive exclamation
            ],
            EmotionState.CONFUSED: [
                re.compile(r"\b(how|why|what|don't understand|clueless|lost|stuck)\b", re.IGNORECASE),
                re.compile(r"\?\?+$"), # Excessive question marks
            ],
            EmotionState.URGENT: [
                re.compile(r"\b(hurry|quick|fast|asap|now|immediately|critical|emergency)\b", re.IGNORECASE),
            ]
        }

    def detect_emotion(self, text: str, last_emotion: EmotionState = EmotionState.CALM) -> EmotionState:
        if not text:
            return last_emotion

        # Priority 1: Frustration
        for p in self._patterns[EmotionState.FRUSTRATED]:
            if p.search(text):
                return EmotionState.FRUSTRATED

        # Priority 2: Urgency
        for p in self._patterns[EmotionState.URGENT]:
            if p.search(text):
                return EmotionState.URGENT

        # Priority 3: Confusion
        for p in self._patterns[EmotionState.CONFUSED]:
            if p.search(text):
                return EmotionState.CONFUSED

        # Default/Decay towards Calm
        return EmotionState.CALM
