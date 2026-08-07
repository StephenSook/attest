"""One definition of what counts as the same character.

Real transcription emits typographic apostrophes, and every contraction in the
cue lexicons is written with the ASCII quote. "We aren't taking new patients"
and the same sentence with U+2019 in place of that quote differ by one codepoint
and used to extract opposite answers. The same codepoint also flipped an
identity correction into a denial in the shipped skill.

The map is one character to one character, so the character offsets of every
cited span are unchanged, which is what lets this run before matching rather
than requiring a second pass to repair offsets. Mirrored in
skills/verify-by-phone/scripts/extract_answer.py and pinned by the parity tests.
"""

_TYPOGRAPHIC = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u02bc": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2013": "-",
        "\u2014": "-",
    }
)


def normalize(text: str) -> str:
    """Lowercase and fold typographic punctuation, preserving length."""
    return text.translate(_TYPOGRAPHIC).lower()
