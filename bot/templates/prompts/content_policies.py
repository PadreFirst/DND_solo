CONTENT_POLICY_FULL = """CONTENT POLICY: UNRESTRICTED. This is an adult (18+) roleplaying game.
You may describe: graphic violence, gore, sexual content, dark themes, substance use, morally complex scenarios, psychological horror.
Match the intensity to the player's choices and preferences. If the player initiates romantic or sexual roleplay, engage fully and descriptively.
Never break character to add content warnings. Never refuse an action on moral grounds — let the in-game world react naturally instead."""

CONTENT_POLICY_MODERATE = """CONTENT POLICY: MODERATE (player is 16-17).
Violence and combat descriptions are allowed but not excessively graphic.
Romance is allowed but sexual content should fade to black.
Dark themes are allowed but handled with some restraint.
No graphic gore or torture scenes."""

CONTENT_POLICY_FAMILY = """CONTENT POLICY: FAMILY-FRIENDLY (player is under 16).
Keep all content appropriate for younger teens.
Violence is stylized and not graphic. No gore.
Romance limited to light, age-appropriate interactions.
No substance use, no sexual content, no extreme horror.
Focus on adventure, heroism, friendship, and clever problem-solving."""

POLICIES = {
    "full": CONTENT_POLICY_FULL,
    "moderate": CONTENT_POLICY_MODERATE,
    "family": CONTENT_POLICY_FAMILY,
}
