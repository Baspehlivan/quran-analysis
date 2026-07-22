from pathlib import Path
from quran_analysis.sources.pipe import parse_source

REAL_SOURCE = Path('data/incoming/quran-uthmani-v1.1v.txt')


def test_tanzil_real_source_classification_counts():
    d = parse_source(REAL_SOURCE, 'tanzil-text-with-ayah-numbers-v1')
    assert d.numbered_ayah_count == 6236
    assert d.non_quran_record_count == 30
    assert d.classifications == {'ayah_record': 6236, 'blank': 2, 'license': 10, 'comment': 11, 'source_metadata': 7}
    assert not d.unknown_lines
    assert not d.malformed
