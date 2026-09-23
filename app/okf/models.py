from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class OKFProvenance(BaseModel):
    source_id: str = Field(..., description="Unique ID of the source document")
    source_title: str = Field(default="", description="Title or name of the source")
    source_url: str = Field(default="", description="URL or filepath of the source")
    chunk_id: Optional[str] = Field(default=None, description="Specific chunk ID where this was found")
    page_number: Optional[int] = Field(default=None, description="Page number if applicable")
    section: Optional[str] = Field(default=None, description="Document section or header")
    extracted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    extractor: str = Field(default="groq/llama-3.3-70b-versatile")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)

class OKFRelationship(BaseModel):
    id: str = Field(..., description="Unique ID of relationship")
    source: str = Field(..., description="Name of source concept")
    target: str = Field(..., description="Name of target concept")
    relation_type: str = Field(
        ...,
        description="Type of relationship: e.g. IMPLEMENTS, USES, EXTENDS, EVALUATED_ON, ENABLES, CAUSES, PART_OF, CONTRADICTS",
    )
    description: str = Field(default="", description="Explanation of how they are related")
    evidence_quote: str = Field(default="", description="Direct verbatim excerpt from source")
    doc_id: str = Field(default="")
    chunk_id: Optional[str] = Field(default=None)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)

class OKFConcept(BaseModel):
    id: str = Field(..., description="Unique concept ID e.g. concept_transformer")
    name: str = Field(..., description="Primary name of concept")
    category: str = Field(
        default="Entity",
        description="Category/Type e.g. Entity, Mechanism, Protocol, Metric, Architecture, Theory, Tool, Dataset",
    )
    definition: str = Field(..., description="Clear, authoritative technical definition")
    aliases: List[str] = Field(default_factory=list, description="Alternative names or acronyms")
    provenance: OKFProvenance = Field(..., description="Provenance metadata")
    components: Dict[str, str] = Field(default_factory=dict, description="Key components and their descriptions")
    relationships: List[OKFRelationship] = Field(default_factory=list)
    mention_count: int = Field(default=1)
    tags: List[str] = Field(default_factory=list)

class OKFSource(BaseModel):
    id: str = Field(..., description="Unique source document ID")
    title: str = Field(..., description="Document title")
    source_type: str = Field(..., description="pdf, url, or markdown/txt")
    source_path_or_url: str = Field(...)
    author: Optional[str] = Field(default="")
    published_date: Optional[str] = Field(default="")
    summary: Optional[str] = Field(default="")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    total_chunks: int = Field(default=0)
    total_concepts: int = Field(default=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    source_title: str
    source_type: str
    content: str
    cleaned_content: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    chunk_index: int = 0
    token_count: int = 0
    concepts: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class OKFDocumentBundle(BaseModel):
    okf_version: str = "1.0"
    source: OKFSource
    concepts: List[OKFConcept] = Field(default_factory=list)
    relationships: List[OKFRelationship] = Field(default_factory=list)
    chunks: List[DocumentChunk] = Field(default_factory=list)

class CitationItem(BaseModel):
    citation_id: int
    quote: str
    source_id: str
    source_title: str
    source_url_or_path: str
    page: Optional[int] = None

class ConfidenceProvenance(BaseModel):
    score: float = Field(default=0.9, ge=0.0, le=1.0)
    rating: str = Field(default="High", description="High, Medium, or Low")
    rationale: str = Field(default="Grounding verification based on retrieved chunks and OKF concept graph.")
    sources_consulted: int = 0
    concepts_linked: int = 0

class ResearchAnswer(BaseModel):
    query: str
    answer: str
    sources: List[OKFSource] = Field(default_factory=list)
    citations: List[CitationItem] = Field(default_factory=list)
    related_concepts: List[OKFConcept] = Field(default_factory=list)
    confidence_provenance: ConfidenceProvenance = Field(default_factory=ConfidenceProvenance)
    retrieved_chunks: List[DocumentChunk] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
