"""Export-only crosswalks from the 2026 Template Framework workbook and DMP4NFDI catalog.

Keep these separate from the reversible RADAR vocabularies: DFG mappings can be
many-to-one or one-to-many and cannot safely be reversed during import.
"""

# [neu]Mapping Fachgebiet.html; keys are research_fields option URI suffixes.
SUBJECTS = {
    '169': ('Other',),
    '170': ('Other',),
    '171': ('Arts and Media',),
    '172': ('Other',),
    '173': ('Linguistics',),
    '174': ('History',),
    '175': ('Theology',),
    '176': ('Philosophy',),
    '177': ('Psychology',),
    '178': ('Other',),
    '179': ('Social Sciences',),
    '180': ('Economics',),
    '181': ('Other',),
    '182': ('Biology', 'Life Science', 'Medicine'),
    '183': ('Other',),
    '184': ('Medicine', 'Other'),
    '185': ('Medicine',),
    '186': ('Other',),
    '187': ('Other',),
    '188': ('Agriculture', 'Veterinary Medicine', 'Horticulture'),
    '189': ('Chemistry', 'Other'),
    '190': ('Chemistry', 'Other'),
    '191': ('Chemistry', 'Other'),
    '192': ('Chemistry', 'Other'),
    '193': ('Biochemistry', 'Other'),
    '194': ('Chemistry', 'Other'),
    '195': ('Physics', 'Other'),
    '196': ('Physics', 'Other'),
    '197': ('Physics', 'Other'),
    '198': ('Physics', 'Other'),
    '199': ('Astrophysics and Astronomy',),
    '200': ('Mathematics',),
    '201': ('Other',),
    '202': ('Geological Science',),
    '203': ('Other',),
    '204': ('Other',),
    '205': ('Other',),
    '206': ('Geography',),
    '207': ('Other',),
    '208': ('Other',),
    '209': ('Other',),
    '210': ('Other',),
    '211': ('Other',),  # Workbook: "Materials Science ?"; deliberately unresolved.
    '212': ('Materials Science',),
    '213': ('Other',),
    '214': ('Other',),
    '215': ('Computer Science', 'Information Technology', 'Software Technology'),
    '216': ('Architecture',),
}
SUBJECT_OPTIONS = {f'research_fields/{key}': value for key, value in SUBJECTS.items()}

CREATION_METHOD_OPTIONS = {
    f'dfg_new_data/dfg-nd_{index:02}': (
        'Observation' if index == 0 else 'Survey' if index in (1, 2) else 'Trial' if index in (3, 4, 5) else 'Other'
    )
    for index in range(15)
}

SOFTWARE_REQUIREMENT = 'dmp4nfdi/v2-0-0/ur00'

# Complete DMP4NFDI planned PID systems in canonical RADAR spelling. The primary
# reader filters these to its narrower schema vocabulary. None means no specific
# controlled scheme; this table does not establish a related-identifier mapping.
PID_SYSTEM_OPTIONS = {
    'https://dmp.service.base4nfdi.de/terms/options/pid00': 'ARK',
    'https://dmp.service.base4nfdi.de/terms/options/pid01': 'arXiv',
    'https://dmp.service.base4nfdi.de/terms/options/pid02': 'bibcode',
    'https://dmp.service.base4nfdi.de/terms/options/pid03': 'DOI',
    'https://dmp.service.base4nfdi.de/terms/options/pid04': 'EAN13',
    'https://dmp.service.base4nfdi.de/terms/options/pid05': 'EISSN',
    'https://dmp.service.base4nfdi.de/terms/options/pid06': 'Handle',
    'https://dmp.service.base4nfdi.de/terms/options/pid07': 'IGSN',
    'https://dmp.service.base4nfdi.de/terms/options/pid08': 'ISBN',
    'https://dmp.service.base4nfdi.de/terms/options/pid09': 'ISSN',
    'https://dmp.service.base4nfdi.de/terms/options/pid10': 'ISTC',
    'https://dmp.service.base4nfdi.de/terms/options/pid11': 'LISSN',
    'https://dmp.service.base4nfdi.de/terms/options/pid12': 'LSID',
    'https://dmp.service.base4nfdi.de/terms/options/pid13': 'PMID',
    'https://dmp.service.base4nfdi.de/terms/options/pid14': 'PURL',
    'https://dmp.service.base4nfdi.de/terms/options/pid15': 'UPC',
    'https://dmp.service.base4nfdi.de/terms/options/pid16': 'URL',
    'https://dmp.service.base4nfdi.de/terms/options/pid17': 'URN',
    'https://dmp.service.base4nfdi.de/terms/options/pid18': None,
}
