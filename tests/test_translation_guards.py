import pytest
from app.translation import should_translate

def test_short_text():
    # Texts shorter than 4 chars or mostly emoji should return False
    assert should_translate("Hi", "en")[0] is False
    assert should_translate("Ok", "en")[0] is False
    assert should_translate("Ya", "id")[0] is False
    assert should_translate("👍", "en")[0] is False

def test_same_language():
    # English text with English target should return False
    assert should_translate("Hello everyone, how are you doing today?", "en")[0] is False
    # Indonesian text with Indonesian target should return False
    assert should_translate("Halo semua, apa kabar hari ini?", "id")[0] is False

def test_id_ms_equivalence():
    # Malay text with Indonesian target should return False
    assert should_translate("Apa khabar semua? Saya harap awak sihat.", "id")[0] is False
    # Indonesian text with Malay target should return False
    assert should_translate("Apa kabar semua? Saya harap kamu sehat.", "ms")[0] is False

def test_real_foreign():
    # Spanish text with English target should return True
    assert should_translate("Hola, ¿cómo estás? Necesito ayuda.", "en")[0] is True
    # English text with Indonesian target should return True
    assert should_translate("Hello, how are you doing today?", "id")[0] is True

def test_low_confidence_gibberish():
    # Ambiguous short text with low confidence should return False
    assert should_translate("asdf lkjh", "en")[0] is False
    assert should_translate("12345 67890", "en")[0] is False
