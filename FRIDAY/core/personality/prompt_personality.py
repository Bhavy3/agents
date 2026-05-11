from .models import PersonaMode, StyleConfig


class PersonalityPromptInjector:
    """Injects personality instructions into LLM prompts."""

    def get_style_instructions(self, config: StyleConfig, mode: PersonaMode) -> str:
        instructions = [
            f"Tonal guideline: {config.tone}.",
            f"Response length: {config.verbosity}.",
            f"Speaking pace: {config.pacing}."
        ]

        # Mode specific nuances
        if mode == PersonaMode.ENGINEERING:
            instructions.append("Focus on technical accuracy, efficiency, and code quality. Avoid unnecessary pleasantries.")
        elif mode == PersonaMode.TEACHING:
            instructions.append("Explain concepts step-by-step. Use analogies. Ensure the user follows your logic.")
        elif mode == PersonaMode.CASUAL:
            instructions.append("Use a relaxed, helpful tone. It is okay to be slightly informal and use subtle humor.")
        
        if config.humor_level > 0.5:
            instructions.append("Occasional dry wit or subtle humor is encouraged, but maintain professionalism.")
        elif config.humor_level == 0.0:
            instructions.append("Absolute zero humor. Be strictly professional and task-focused.")

        return "\n[PERSONALITY_GUIDELINES]\n" + "\n".join(instructions) + "\n"
