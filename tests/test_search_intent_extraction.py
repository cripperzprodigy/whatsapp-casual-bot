import pytest
from app.utils.search_intent import detect_search_intent

@pytest.mark.parametrize("input_text, expected_query", [
    ("search the web for batam news", "batam news"),
    ("can you look up latest fifa results", "latest fifa results"),
    ("google singapore weather", "singapore weather"),
    ("find me a recipe for laksa", "a recipe for laksa"),
])
def test_search_intent_extraction(input_text, expected_query):
    is_search, extracted = detect_search_intent(input_text)
    assert is_search is True
    assert extracted == expected_query

def test_search_intent_false_positives():
    is_search, query = detect_search_intent("find it")
    assert is_search is False
    
    is_search, query = detect_search_intent("I looked for my keys")
    assert is_search is False
