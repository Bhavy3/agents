from .models import PersonaMode, EmotionState, StyleConfig


class StyleEngine:
    """Calculates response style based on user emotion, persona mode, and context."""

    def compute_style(
        self, 
        mode: PersonaMode, 
        emotion: EmotionState, 
        is_task_active: bool = False
    ) -> StyleConfig:
        
        # Base styles for modes
        if mode == PersonaMode.ENGINEERING:
            config = StyleConfig(tone="focused", verbosity="concise", pacing="normal", humor_level=0.1)
        elif mode == PersonaMode.TEACHING:
            config = StyleConfig(tone="patient", verbosity="detailed", pacing="slow", humor_level=0.3)
        elif mode == PersonaMode.CASUAL:
            config = StyleConfig(tone="friendly", verbosity="normal", pacing="normal", humor_level=0.6)
        else: # Stress mode
            config = StyleConfig(tone="supportive", verbosity="concise", pacing="fast", humor_level=0.0)

        # Emotion overrides (Safety/Empathy layer)
        if emotion == EmotionState.FRUSTRATED:
            # Drop the fluff, get to the point fast
            return StyleConfig(
                tone="direct",
                verbosity="concise",
                pacing="fast",
                humor_level=0.0
            )
        
        if emotion == EmotionState.URGENT:
            return StyleConfig(
                tone="alert",
                verbosity="concise",
                pacing="fast",
                humor_level=0.0
            )

        if emotion == EmotionState.CONFUSED:
            # Slow down and explain more
            return StyleConfig(
                tone="clarifying",
                verbosity="detailed",
                pacing="slow",
                humor_level=config.humor_level
            )

        # Contextual adjustments
        if is_task_active and config.verbosity == "detailed":
            # Don't overwhelm during active work
            config = StyleConfig(
                tone=config.tone,
                verbosity="normal",
                pacing=config.pacing,
                humor_level=config.humor_level * 0.5
            )

        return config
