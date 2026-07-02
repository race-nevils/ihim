"""Punctuation regressions from the 2026-07-02 dictation logs.

Two distinct bugs, both proven from raw-vs-cleaned JSONL records:
 1. Whisper's raw output lost periods/colons — the hotwords prompt was
    an unpunctuated comma-list injected into every decode window, and
    Whisper mimics its prompt's style (openai/whisper #625).
 2. Cleanup converted the spoken NOUN "colon" into ":" ("the colon is
    missing" → "the: is missing") — verbal punctuation commands fired
    without checking for a preceding determiner.
"""

import tools.stt.transcribe as transcribe
from tools.stt.cleanup import _apply_punctuation_commands, cleanup_transcript


# ---------------------------------------------------------------------------
# _load_vocab — hotwords must carry punctuated, cased style
# ---------------------------------------------------------------------------

class TestVocabPrompt:
    def test_vocab_wrapped_in_punctuated_sentence(self, tmp_path, monkeypatch):
        vocab = tmp_path / "vocab.txt"
        vocab.write_text("the agent harness\niHIM\nEdgeFlow\n", encoding="utf-8")
        monkeypatch.setattr(transcribe, "VOCAB_FILE", vocab)

        prompt = transcribe._load_vocab()
        assert "the agent harness, iHIM, EdgeFlow" in prompt
        # Cased, sentence-shaped context — not a bare comma-list.
        assert prompt[0].isupper()
        assert ". " in prompt
        assert prompt.endswith(".")

    def test_missing_vocab_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(transcribe, "VOCAB_FILE", tmp_path / "absent.txt")
        assert transcribe._load_vocab() == ""

    def test_empty_vocab_file_returns_empty(self, tmp_path, monkeypatch):
        vocab = tmp_path / "vocab.txt"
        vocab.write_text("\n\n", encoding="utf-8")
        monkeypatch.setattr(transcribe, "VOCAB_FILE", vocab)
        assert transcribe._load_vocab() == ""


# ---------------------------------------------------------------------------
# Punctuation commands — determiner means noun, not command
# ---------------------------------------------------------------------------

class TestDeterminerGuard:
    def test_the_colon_is_a_noun(self):
        text = "the colon is missing in between 12 and 43 AM"
        assert _apply_punctuation_commands(text) == text

    def test_a_period_is_a_noun(self):
        text = "there should be a period at the end"
        assert _apply_punctuation_commands(text) == text

    def test_this_comma_is_a_noun(self):
        text = "this comma looks wrong"
        assert _apply_punctuation_commands(text) == text

    def test_bare_command_still_fires(self):
        assert _apply_punctuation_commands("done period next item") == "done. next item"

    def test_bare_colon_command_still_fires(self):
        assert _apply_punctuation_commands("note colon buy milk") == "note: buy milk"

    def test_word_ending_in_a_does_not_shield(self):
        # "extra" ends in "a" but is not the determiner "a".
        assert _apply_punctuation_commands("extra comma here") == "extra, here"

    def test_race_sentence_end_to_end(self):
        raw = (
            "Also in that transcription that I just did, the colon is missing "
            "in between 12 and 43 AM. So even right there it's proof of the bug."
        )
        assert "the colon is missing" in cleanup_transcript(raw)
