"""Candidate review of observed entry facts, never a completed transaction."""

def review_entries(entries):
    observations = []
    for entry in entries:
        fact = entry['detail_fact']
        observations.append({'offer': fact['business_key'], 'catalog_price': entry['catalog_fact']['price'],
                             'stage': 'selection_seen', 'rights': 'not_observed', 'checkout': 'not_observed'})
    return observations
