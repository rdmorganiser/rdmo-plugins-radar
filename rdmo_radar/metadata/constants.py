import re

SCHEME_URIS = {
    'ORCID': 'https://orcid.org/',
    'ROR': 'https://ror.org/',
    'GND': 'https://d-nb.info/gnd/',
}

KEYWORD_ATTRIBUTES = (
    ('keyword_scheme', 'keywordScheme'),
    ('scheme_uri', 'schemeURI'),
    ('value_uri', 'valueURI'),
    ('classification_code', 'classificationCode'),
)


_API_OVERRIDES = {
    'arXiv': 'ARXIV',
    'bibcode': 'BIBCODE',
    'Handle': 'HANDLE',
    'ePIC': 'EPIC',
    'RAiD': 'RAID',
    'w3id': 'W3ID',
    'Personal': 'Personal',
    'Organizational': 'Organizational',
    'CC BY 4.0 Attribution': 'CC_BY_4_0_ATTRIBUTION',
    'CC BY-ND 4.0 Attribution-NoDerivs': 'CC_BY_ND_4_0_ATTRIBUTION_NO_DERIVS',
    'CC BY-SA 4.0 Attribution-ShareAlike': 'CC_BY_SA_4_0_ATTRIBUTION_SHARE_ALIKE',
    'CC BY-NC 4.0 Attribution-NonCommercial': 'CC_BY_NC_4_0_ATTRIBUTION_NON_COMMERCIAL',
    'CC0 1.0 Universal Public Domain Dedication': 'CC_0_1_0_UNIVERSAL_PUBLIC_DOMAIN_DEDICATION',
}


def to_api_value(value: str | None) -> str | None:
    if value is None:
        return None
    if value in _API_OVERRIDES:
        return _API_OVERRIDES[value]
    value = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', value)
    value = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', value)
    return re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_').upper()
