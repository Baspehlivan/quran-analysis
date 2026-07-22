from pathlib import Path
from quran_analysis.sources.pipe import parse_pipe_ayah_v1
from quran_analysis.sources.register import register_source
from quran_analysis.ingestion.memory import ingest_memory, validate_reconstruction
from quran_analysis.tokenization.core import tokenize_reversible, reconstruct_from_tokens
from quran_analysis.normalization.profiles import normalize_token
from quran_analysis.scopes.core import numbered_only, scope_hash

FIXTURE=Path('tests/fixtures/sample-pipe.txt')

def test_strict_pipe_preserves_text_and_reports():
    d=parse_pipe_ayah_v1(FIXTURE.read_text(encoding='utf-8'))
    assert d.records[0].text == ' alpha beta'
    assert d.surah_count == 2
    assert not d.malformed

def test_registration_deterministic(tmp_path):
    r1=register_source(FIXTURE,'sample','v1','pipe-ayah-v1',tmp_path)
    r2=register_source(FIXTURE,'sample','v1','pipe-ayah-v1',tmp_path)
    assert r1['status']==r2['status']=='registered'
    assert r1['manifest']['stored_filename']==r2['manifest']['stored_filename']
    assert (tmp_path/'raw'/r1['manifest']['stored_filename']).read_bytes()==FIXTURE.read_bytes()

def test_token_reconstruction():
    toks=tokenize_reversible(' alpha beta')
    assert reconstruct_from_tokens(toks) == ' alpha beta'
    assert [t['surface_raw'] for t in toks] == ['alpha','beta']

def test_ingestion_reconstruction_unicode_graphemes_counts_search():
    st=ingest_memory(FIXTURE)
    assert len(st['units']) == 3
    assert validate_reconstruction(st)['ok']
    assert ''.join(cp['character'] for cp in st['units'][1]['codepoints']) == 'gamma\u0301 delta'
    assert any(g['raw_value']=='a\u0301' for g in st['units'][1]['graphemes'])
    assert sum(1 for u in st['units'] for t in u['tokens'] if t['surface_raw']=='epsilon') == 1

def test_normalization_log_and_scope_hash():
    result=normalize_token('a\u0301','remove_combining_marks_v1')
    assert result['normalized_value']=='a'
    assert any(x['action']=='drop' for x in result['transformation_log'])
    assert scope_hash(numbered_only()) == scope_hash(numbered_only())

def test_prohibited_no_special_expected_patterns():
    for path in Path('src').rglob('*.py'):
        body=path.read_text(encoding='utf-8')
        assert '6236' not in body
        assert 'numerolog' not in body.lower()
