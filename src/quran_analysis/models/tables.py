from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from quran_analysis.models.base import Base
JSONType = JSON().with_variant(JSONB, "postgresql")
class SourceRelease(Base):
    __tablename__ = "source_release"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(200))
    source_version: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text())
    source_format: Mapped[str] = mapped_column(String(50))
    original_filename: Mapped[str] = mapped_column(Text())
    stored_filename: Mapped[str] = mapped_column(Text())
    encoding: Mapped[str] = mapped_column(String(40), default="utf-8")
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    byte_size: Mapped[int]
    line_count: Mapped[int]
    registered_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    license: Mapped[str | None] = mapped_column(Text())
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    notes: Mapped[str | None] = mapped_column(Text())
    __table_args__ = (UniqueConstraint("source_name", "source_version"), CheckConstraint("byte_size >= 0"), CheckConstraint("line_count >= 0"))

class SourceLine(Base):
    __tablename__ = "source_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_release_id: Mapped[int] = mapped_column(ForeignKey("source_release.id"))
    source_line_number: Mapped[int]
    record_type: Mapped[str] = mapped_column(String(40))
    raw_line_content: Mapped[str] = mapped_column(Text())
    line_ending: Mapped[str] = mapped_column(String(4))
    byte_start: Mapped[int]
    byte_end: Mapped[int]
    classification_reason: Mapped[str] = mapped_column(Text())
    parsed_text_unit_id: Mapped[int | None] = mapped_column(ForeignKey("text_unit.id"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (
        UniqueConstraint("source_release_id", "source_line_number"),
        CheckConstraint("record_type in ('ayah_record','blank','source_metadata','license','comment','unknown')"),
        CheckConstraint("source_line_number > 0"),
        CheckConstraint("byte_start >= 0"),
        CheckConstraint("byte_end >= byte_start"),
    )

class AnalyticalCharacter(Base):
    __tablename__ = "analytical_character"
    id: Mapped[int] = mapped_column(primary_key=True)
    unicode_codepoint_id: Mapped[int] = mapped_column(ForeignKey("unicode_codepoint.id"))
    source_release_id: Mapped[int] = mapped_column(ForeignKey("source_release.id"))
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_unit.id"))
    address_space: Mapped[str] = mapped_column(String(80), default="source_release_codepoint_v1")
    position_in_address_space: Mapped[int]
    character: Mapped[str] = mapped_column(Text())
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (UniqueConstraint("source_release_id", "address_space", "position_in_address_space"),)
class Surah(Base):
    __tablename__ = "surah"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_release_id: Mapped[int] = mapped_column(ForeignKey("source_release.id"))
    surah_number: Mapped[int]
    source_order: Mapped[int]
    arabic_name: Mapped[str | None] = mapped_column(Text())
    transliterated_name: Mapped[str | None] = mapped_column(Text())
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (UniqueConstraint("source_release_id", "surah_number"), UniqueConstraint("source_release_id", "source_order"), CheckConstraint("surah_number > 0"), CheckConstraint("source_order > 0"))
class TextUnit(Base):
    __tablename__ = "text_unit"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_release_id: Mapped[int] = mapped_column(ForeignKey("source_release.id"))
    surah_id: Mapped[int] = mapped_column(ForeignKey("surah.id"))
    unit_type: Mapped[str] = mapped_column(String(40))
    surah_number: Mapped[int]
    ayah_number: Mapped[int | None]
    source_order: Mapped[int]
    global_numbered_ayah_position: Mapped[int | None]
    text_raw: Mapped[str] = mapped_column(Text())
    source_line_number: Mapped[int | None]
    source_byte_start: Mapped[int | None]
    source_byte_end: Mapped[int | None]
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (UniqueConstraint("source_release_id", "source_order"), UniqueConstraint("source_release_id", "global_numbered_ayah_position"), CheckConstraint("source_order > 0"))
class OrthographicToken(Base):
    __tablename__ = "orthographic_token"
    id: Mapped[int] = mapped_column(primary_key=True)
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_unit.id"))
    token_in_unit: Mapped[int]
    token_in_surah: Mapped[int]
    token_in_numbered_stream: Mapped[int | None]
    token_in_full_source_stream: Mapped[int]
    surface_raw: Mapped[str] = mapped_column(Text())
    delimiter_before: Mapped[str] = mapped_column(Text(), default="")
    delimiter_after: Mapped[str] = mapped_column(Text(), default="")
    start_codepoint_in_unit: Mapped[int]
    end_codepoint_in_unit: Mapped[int]
    start_byte_in_unit: Mapped[int | None]
    end_byte_in_unit: Mapped[int | None]
    tokenizer_version: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("text_unit_id", "token_in_unit"),)
class UnicodeCodepoint(Base):
    __tablename__ = "unicode_codepoint"
    id: Mapped[int] = mapped_column(primary_key=True)
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_unit.id"))
    orthographic_token_id: Mapped[int | None] = mapped_column(ForeignKey("orthographic_token.id"))
    codepoint_in_text_unit: Mapped[int]
    codepoint_in_token: Mapped[int | None]
    codepoint_in_numbered_stream: Mapped[int | None]
    codepoint_in_full_source_stream: Mapped[int]
    character: Mapped[str] = mapped_column(Text())
    unicode_hex: Mapped[str] = mapped_column(String(12))
    unicode_name: Mapped[str] = mapped_column(Text())
    general_category: Mapped[str] = mapped_column(String(4))
    canonical_combining_class: Mapped[int]
    is_combining_mark: Mapped[bool]
    is_whitespace: Mapped[bool]
    is_punctuation: Mapped[bool]
    is_quranic_annotation: Mapped[bool]
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (UniqueConstraint("text_unit_id", "codepoint_in_text_unit"),)
class GraphemeCluster(Base):
    __tablename__ = "grapheme_cluster"
    id: Mapped[int] = mapped_column(primary_key=True)
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_unit.id"))
    orthographic_token_id: Mapped[int | None] = mapped_column(ForeignKey("orthographic_token.id"))
    grapheme_in_text_unit: Mapped[int]
    grapheme_in_token: Mapped[int | None]
    raw_value: Mapped[str] = mapped_column(Text())
    start_codepoint_in_text_unit: Mapped[int]
    end_codepoint_in_text_unit: Mapped[int]
    segmentation_version: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("text_unit_id", "grapheme_in_text_unit"),)
class NormalizationProfile(Base):
    __tablename__ = "normalization_profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text())
    configuration_json: Mapped[dict] = mapped_column(JSONType)
    configuration_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    is_frozen: Mapped[bool] = mapped_column(Boolean(), default=True)
    __table_args__ = (UniqueConstraint("name", "version"),)
class NormalizedToken(Base):
    __tablename__ = "normalized_token"
    id: Mapped[int] = mapped_column(primary_key=True)
    orthographic_token_id: Mapped[int] = mapped_column(ForeignKey("orthographic_token.id"))
    normalization_profile_id: Mapped[int] = mapped_column(ForeignKey("normalization_profile.id"))
    normalized_value: Mapped[str] = mapped_column(Text())
    transformation_log_json: Mapped[list] = mapped_column(JSONType)
    profile_configuration_sha256: Mapped[str] = mapped_column(String(64), default="")
    normalized_to_source_codepoint_ids_json: Mapped[list] = mapped_column(JSONType, default=list)
    __table_args__ = (UniqueConstraint("orthographic_token_id", "normalization_profile_id"),)
class QueryScopeDefinition(Base):
    __tablename__ = "query_scope_definition"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text())
    configuration_json: Mapped[dict] = mapped_column(JSONType)
    configuration_sha256: Mapped[str] = mapped_column(String(64))
    is_frozen: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("name", "version"),)
class AnalysisRun(Base):
    __tablename__ = "analysis_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_type: Mapped[str] = mapped_column(String(80))
    source_release_id: Mapped[int] = mapped_column(ForeignKey("source_release.id"))
    scope_configuration_json: Mapped[dict] = mapped_column(JSONType)
    normalization_profile_id: Mapped[int | None] = mapped_column(ForeignKey("normalization_profile.id"))
    tokenizer_version: Mapped[str] = mapped_column(String(40))
    software_version: Mapped[str] = mapped_column(String(40))
    query_parameters_json: Mapped[dict] = mapped_column(JSONType)
    query_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime())
    status: Mapped[str] = mapped_column(String(40))
    result_count: Mapped[int | None]
    result_manifest_path: Mapped[str | None] = mapped_column(Text())
    error_message: Mapped[str | None] = mapped_column(Text())
class AnalysisEvidence(Base):
    __tablename__ = "analysis_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_run.id"))
    result_index: Mapped[int]
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_unit.id"))
    orthographic_token_id: Mapped[int | None] = mapped_column(ForeignKey("orthographic_token.id"))
    codepoint_start: Mapped[int | None]
    codepoint_end: Mapped[int | None]
    raw_value: Mapped[str] = mapped_column(Text())
    normalized_value: Mapped[str | None] = mapped_column(Text())
    inclusion_reason: Mapped[str] = mapped_column(Text())
    evidence_json: Mapped[dict] = mapped_column(JSONType, default=dict)
