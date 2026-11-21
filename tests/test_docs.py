"""Document search tests: pure math and text, no internet, no API key."""
import numpy as np

import docs


def test_chunking_keeps_page_numbers():
    chunks = docs.chunk_pages([(1, "x" * 5000), (2, "short page")], max_chars=3000, overlap=300)
    assert [c["page"] for c in chunks] == [1, 1, 2]       # a long page splits in two; each chunk knows its page


def test_rank_returns_most_similar_first():
    matrix = np.array([[1, 0], [0, 1], [0.9, 0.1]], dtype=np.float32)
    assert docs.rank(matrix, np.array([1, 0], dtype=np.float32), k=2)[0][0] == 0


def test_keyword_search_finds_rare_exact_word():
    texts = ["bond rules for sureties", "the magnitude of this project is between $1,000,000 and $5,000,000",
             "insurance rules"]
    assert docs.keyword_rank(texts, "What is the magnitude of the project?")[0] == 1


def test_fusion_keeps_a_keyword_only_hit():
    by_meaning = [0, 2, 3, 4, 1]                          # meaning search ranked chunk 1 last
    by_keyword = [1, 0, 2, 3, 4]                          # keyword search ranked it first
    assert 1 in docs.fuse(by_meaning, by_keyword, k=3)
