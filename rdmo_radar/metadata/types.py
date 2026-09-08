from dataclasses import dataclass, field


@dataclass
class Identifier:
    value: str
    identifier_type: str | None = None
    relation_type: str | None = None


@dataclass
class Affiliation:
    name: str
    identifier: str | None = None
    identifier_scheme: str | None = None


@dataclass
class Agent:
    name: str
    given_name: str | None = None
    family_name: str | None = None
    name_type: str | None = None
    identifiers: list[Identifier] = field(default_factory=list)
    affiliations: list[Affiliation] = field(default_factory=list)
    contributor_type: str | None = None


@dataclass
class SubjectArea:
    controlled_name: str
    additional_name: str | None = None


@dataclass
class Resource:
    value: str
    resource_type: str | None = None


@dataclass
class Rights:
    controlled: str
    additional: str | None = None


@dataclass
class FundingReference:
    funder_name: str | None = None
    funder_identifier: Identifier | None = None
    award_number: str | None = None
    award_uri: str | None = None
    award_title: str | None = None


@dataclass
class GeoLocation:
    country: str | None = None
    region: str | None = None
    latitude: str | None = None
    longitude: str | None = None


@dataclass
class Software:
    name: str
    software_type: str | None = None
    version: str | None = None
    alternative_name: str | None = None
    alternative_version: str | None = None


@dataclass
class Description:
    value: str
    description_type: str = 'Abstract'


@dataclass
class MappingIssue:
    field: str
    reason: str
    value: str | None = None

    def __str__(self) -> str:
        suffix = f' ({self.value})' if self.value else ''
        return f'{self.field}: {self.reason}{suffix}'


@dataclass
class RadarMetadata:
    identifier: Identifier | None = None
    alternate_identifiers: list[Identifier] = field(default_factory=list)
    related_identifiers: list[Identifier] = field(default_factory=list)
    creators: list[Agent] = field(default_factory=list)
    contributors: list[Agent] = field(default_factory=list)
    title: str | None = None
    additional_titles: list[str] = field(default_factory=list)
    descriptions: list[Description] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    publishers: list[Agent] = field(default_factory=list)
    production_year: str | None = None
    publication_year: str | None = None
    language: str | None = None
    subject_areas: list[SubjectArea] = field(default_factory=list)
    resource: Resource | None = None
    geo_locations: list[GeoLocation] = field(default_factory=list)
    data_sources: list[Resource] = field(default_factory=list)
    software: list[Software] = field(default_factory=list)
    processing: list[str] = field(default_factory=list)
    rights: Rights | None = None
    rights_holders: list[Agent] = field(default_factory=list)
    related_information: list[str] = field(default_factory=list)
    funding_references: list[FundingReference] = field(default_factory=list)
    version: str | None = None
