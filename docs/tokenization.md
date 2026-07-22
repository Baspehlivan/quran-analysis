# Tokenization

Tokenizer version `whitespace-spans-v1` is a reversible orthographic tokenizer. Tokens are maximal non-whitespace spans. Delimiters are non-overlapping: each token owns only `delimiter_before`; `delimiter_after` is retained as an empty compatibility field. A final trailing delimiter, if present after the last token, is stored on `text_unit.metadata_json.final_trailing_delimiter`.

Reconstruction is: concatenate `delimiter_before + surface_raw + delimiter_after` for ordered tokens, then append `final_trailing_delimiter`. This preserves leading, repeated, unusual, and trailing whitespace without duplication or omission.
