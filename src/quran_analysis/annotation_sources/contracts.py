"""Pure, non-persistent contracts for locally acquired annotation sources.

These contracts deliberately do not open files, register sources, parse QAC, write a
DB, or align annotations. Raw physical records are canonical; parsed values are
lossless derivatives that can always be discarded and regenerated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from quran_analysis.provenance import canonical_hash, canonical_json


class SourceClass(str, Enum):
    SYNTHETIC_FIXTURE = "synthetic-fixture"
    USER_LOCAL_DATASET = "user-local-dataset"


@dataclass(frozen=True)
class SourceIdentity:
    source_identifier: str
    source_class: SourceClass
    adapter_identifier: str
    adapter_version: str

    def __post_init__(self) -> None:
        if not all((self.source_identifier, self.adapter_identifier, self.adapter_version)):
            raise ValueError("source and adapter identifiers must be non-empty")


@dataclass(frozen=True)
class SourceFingerprint:
    sha256: str
    sha512: str | None
    byte_count: int
    line_ending: str
    encoding: str

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 hex digest")
        if self.sha512 is not None and (len(self.sha512) != 128 or any(c not in "0123456789abcdef" for c in self.sha512)):
            raise ValueError("sha512 must be a lowercase SHA-512 hex digest")
        if self.byte_count < 0:
            raise ValueError("byte_count cannot be negative")


@dataclass(frozen=True)
class SourceAcquisition:
    acquisition_date: date
    local_filename: str
    original_filename: str
    local_only: bool = True

    def __post_init__(self) -> None:
        if not self.local_filename or not self.original_filename:
            raise ValueError("local and original filenames must be non-empty")


@dataclass(frozen=True)
class SourceIntegrity:
    license: str
    citation: str
    fingerprint: SourceFingerprint


@dataclass(frozen=True)
class ParserConfiguration:
    parser_identifier: str
    parser_version: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.parser_identifier or not self.parser_version:
            raise ValueError("parser identifier and version must be non-empty")

    def canonical_json(self) -> str:
        return canonical_json(asdict(self))


@dataclass(frozen=True)
class ParserConfigurationHash:
    algorithm: str
    digest: str

    @classmethod
    def from_configuration(cls, configuration: ParserConfiguration) -> ParserConfigurationHash:
        return cls(algorithm="sha256-canonical-json-v1", digest=canonical_hash(asdict(configuration)))


@dataclass(frozen=True)
class SourceMetadata:
    identity: SourceIdentity
    acquisition: SourceAcquisition
    integrity: SourceIntegrity
    parser_configuration: ParserConfiguration

    def canonical_json(self) -> str:
        return canonical_json(asdict(self))

    def canonical_hash(self) -> str:
        return canonical_hash(asdict(self))


class PhysicalEnding(bytes, Enum):
    NONE = b""
    LF = b"\n"
    CRLF = b"\r\n"
    CR = b"\r"


class ParserStatus(str, Enum):
    PARSED = "parsed"
    UNKNOWN = "unknown"
    MALFORMED = "malformed"


class RecordKind(str, Enum):
    COMMENT = "comment"
    COPYRIGHT = "copyright"
    HEADER = "header"
    BLANK = "blank"
    MORPHOLOGY = "morphology"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RawRecord:
    """One physical source line, excluding and retaining its exact ending separately."""

    line_number: int
    raw_line_bytes: bytes
    physical_ending: PhysicalEnding
    parser_status: ParserStatus
    decoded_text: str = ""
    record_kind: RecordKind = RecordKind.UNKNOWN

    def __post_init__(self) -> None:
        if self.line_number < 1:
            raise ValueError("line_number is one-based")
        if self.raw_line_bytes.endswith((b"\n", b"\r")):
            raise ValueError("raw_line_bytes must exclude its physical ending")

    def physical_bytes(self) -> bytes:
        return self.raw_line_bytes + self.physical_ending.value


@dataclass(frozen=True)
class SegmentLocator:
    surah: int
    ayah: int
    token: int
    segment: int | None = None

    def __post_init__(self) -> None:
        if self.surah < 1 or self.ayah < 1 or self.token < 1 or (self.segment is not None and self.segment < 1):
            raise ValueError("locator parts must be positive one-based integers")


@dataclass(frozen=True)
class FeatureBundle:
    native: Mapping[str, str]
    raw_text: str = ""
    fragments: tuple[str, ...] = ()
    separator: str = "|"

    def __post_init__(self) -> None:
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.native.items()):
            raise TypeError("feature keys and values must be strings")
        if not isinstance(self.raw_text, str) or not isinstance(self.separator, str):
            raise TypeError("feature text and separator must be strings")
        if any(not isinstance(fragment, str) for fragment in self.fragments):
            raise TypeError("feature fragments must be strings")


@dataclass(frozen=True)
class ParsedRecord:
    """Derived parsed view of a RawRecord; only a raw record marked parsed may have one."""

    raw_record: RawRecord
    locator: SegmentLocator
    features: FeatureBundle
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.raw_record.parser_status is not ParserStatus.PARSED:
            raise ValueError("ParsedRecord requires a raw record with parsed status")


@dataclass(frozen=True)
class ParserError:
    line_number: int
    message: str


@dataclass(frozen=True)
class UnknownRecord:
    raw_record: RawRecord
    reason: str

    def __post_init__(self) -> None:
        if self.raw_record.parser_status is not ParserStatus.UNKNOWN:
            raise ValueError("UnknownRecord requires unknown parser status")


@dataclass(frozen=True)
class MalformedRecord:
    raw_record: RawRecord
    error: ParserError

    def __post_init__(self) -> None:
        if self.raw_record.parser_status is not ParserStatus.MALFORMED:
            raise ValueError("MalformedRecord requires malformed parser status")
        if self.error.line_number != self.raw_record.line_number:
            raise ValueError("parser error line must match its raw record")


@dataclass(frozen=True)
class ParserResult:
    raw_records: Sequence[RawRecord]
    parsed_records: Sequence[ParsedRecord] = ()
    unknown_records: Sequence[UnknownRecord] = ()
    malformed_records: Sequence[MalformedRecord] = ()

    def __post_init__(self) -> None:
        lines = [record.line_number for record in self.raw_records]
        if lines != list(range(1, len(lines) + 1)):
            raise ValueError("raw records must be consecutive physical lines starting at one")
        if reconstruct_physical_bytes(self.raw_records) != b"".join(record.physical_bytes() for record in self.raw_records):
            raise ValueError("raw records must reconstruct exactly")


class QACParser(Protocol):
    """Interface only. No qac-morphology-v0.4 parser is implemented in this phase."""

    identity: SourceIdentity

    def parse(self, raw_records: Sequence[RawRecord], configuration: ParserConfiguration) -> ParserResult: ...


def reconstruct_physical_bytes(records: Sequence[RawRecord]) -> bytes:
    """Rebuild original bytes exactly, including each physical line ending."""
    return b"".join(record.physical_bytes() for record in records)


QAC_MORPHOLOGY_V04_IDENTITY = SourceIdentity(
    source_identifier="qac-morphology-v0.4",
    source_class=SourceClass.USER_LOCAL_DATASET,
    adapter_identifier="qac-morphology-v0.4",
    adapter_version="0.4",
)
