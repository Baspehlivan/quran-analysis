from quran_analysis.tokenization.core import tokenize_reversible, reconstruct_from_tokens, tokenization_metadata


def test_tokenization_preserves_repeated_and_trailing_delimiters():
    text = '  alpha  beta\t'
    tokens = tokenize_reversible(text)
    metadata = tokenization_metadata(tokens)
    assert reconstruct_from_tokens(tokens, metadata['final_trailing_delimiter']) == text
    assert [t['delimiter_before'] for t in tokens] == ['  ', '  ']
    assert metadata['final_trailing_delimiter'] == '\t'
