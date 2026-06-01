"""Text-only STT validation helpers for ARIA voice input."""


CONVERSATION_CONTROL_WORDS = {
    "bye", "goodbye", "good bye", "exit", "pause", "resume", "stop"
}


VALID_SHORT_REPLIES = {
    "ok", "okay", "yes", "yeah", "yep", "no", "nope", "hi", "hello",
    "hey", "continue", "stop", "cancel", "right", "sure", "fine",
    "thanks", "thank you", "absolutely", "amazon", "done", "enough",
    "that's it", "thats it", "हेलो", "हाय", "हाँ", "हा", "नहीं", "ठीक",
    "bye", "goodbye", "good bye", "exit", "pause", "resume"
}

HALLUCINATIONS = [
    "thank you", "thanks for watching", "subtitle by", "bye", "you",
    "yep", "yeah", "uh", "um", "ah", "oh", "ok", "okay", "you guys",
    "thank you very much", "thanks", "i'm out", "perfect", "it's great",
    "great", "goodbye", "good bye", "that's it", "thank you for watching",
    "that's great", "perfect.",
]

ALLOWED_SINGLE_WORDS = {
    "stop", "cancel", "yes", "no", "hi", "hello", "open", "close",
    "restart", "shutdown", "unlock", "status", "lock", "help", "aria",
    "back", "next", "up", "down", "left", "right", "clear", "mute", "unmute",
    "continue", "absolutely", "amazon", "done", "enough", "हेलो", "हाय", "हाँ", "हा", "नहीं", "ठीक",
    "bye", "exit", "pause", "resume"
}


def normalize_transcript(text):
    return (text or "").strip().lower().replace(".", "").replace("!", "").replace("?", "")


def is_valid_speech_text(text, active_conversation=False):
    """Validate transcribed text without importing microphone/TTS dependencies."""
    if not text:
        return False, "empty"

    txt_clean = normalize_transcript(text)

    # Check conversation control commands first (e.g. bypass hallucination filter)
    if txt_clean in CONVERSATION_CONTROL_WORDS:
        return True, "conversation_control"

    if active_conversation and txt_clean in VALID_SHORT_REPLIES:
        return True, "active_short_reply"

    if txt_clean in HALLUCINATIONS:
        return False, "static_silence_hallucination"

    if len(txt_clean) <= 1:
        if not txt_clean.isdigit():
            return False, "ultra_short_noise"

    words = txt_clean.split()
    if len(words) < 2:
        is_numeric = False
        if words:
            try:
                float(words[0])
                is_numeric = True
            except ValueError:
                pass
        if not words or (words[0] not in ALLOWED_SINGLE_WORDS and not is_numeric):
            return False, "single_word_ambient_noise"

    return True, "valid"

