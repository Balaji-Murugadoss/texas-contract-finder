"""Document search tests: pure math and text, no internet, no API key."""
import numpy as np

import docs


def test_chunking_keeps_page_numbers():
    chunks = docs.chunk_pages([(1, "x" * 5000), (2, "short page")], max_chars=3000, overlap=300)
    assert [c["page"] for c in chunks] == [1, 1, 2]       # a long page splits in two; each chunk knows its page


def test_rank_returns_most_similar_first():
    matrix = np.array([[1, 0], [0, 1], [0.9, 0.1]], dtype=np.float32)
    assert docs.rank(matrix, np.array([1, 0], dtype=np.float32), k=2)[0][0] == 0
