import pytest
from app.translation import detect_language_safe

def test_length_and_word_guards():
    # Length < 10 should return None
    assert detect_language_safe("Hi", "en") is None
    assert detect_language_safe("Shortest", "en") is None
    
    # Words < 3 should return None (even if length > 10)
    assert detect_language_safe("LongWordHere Indeed", "en") is None
    
    # Emoji should return None
    assert detect_language_safe("👍👍👍👍👍👍👍👍👍👍👍👍👍", "en") is None

def test_same_language():
    # English text with English target should return None
    assert detect_language_safe("Hello everyone, how are you doing today?", "en") is None
    # Indonesian text with Indonesian target should return None
    assert detect_language_safe("Halo semua, apa kabar hari ini?", "id") is None

def test_id_ms_equivalence():
    # Malay text with Indonesian target should return None
    assert detect_language_safe("Apa khabar semua? Saya harap awak sihat.", "id") is None
    # Indonesian text with Malay target should return None
    assert detect_language_safe("Apa kabar semua? Saya harap kamu sehat.", "ms") is None

def test_real_foreign():
    # Spanish text with English target should return the code ('es')
    assert detect_language_safe("Hola, ¿cómo estás? Necesito ayuda.", "en") == "es"
    # English text with Indonesian target should return the code ('en')
    assert detect_language_safe("Hello, how are you doing today?", "id") == "en"

def test_low_confidence_gibberish():
    # Ambiguous short text with low confidence should return None
    assert detect_language_safe("asdf lkjh", "en") is None
    assert detect_language_safe("12345 67890", "en") is None
