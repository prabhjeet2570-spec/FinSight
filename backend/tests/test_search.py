from app.search import bm25, rrf

def test_bm25_exact_phrase_and_no_match():
    scores=bm25('supply chain', ['Supply chain disruptions reduce shipments.', 'Cloud revenue grew.', 'The chain is a supply chain.'])
    assert scores[0]>scores[1] and scores[2]>scores[1]
    assert bm25('unobtainium',['nothing relevant']) == [0]

def test_fusion_uses_ranks_not_incompatible_score_scales():
    scores=rrf([['a','b'],['b','c']])
    assert scores['b']>scores['a']>scores['c']
