# semantic-chunking Specification

## Purpose

Provides semantic chunking for document ingestion: documents are split into semantic parent chunks by sentence-level embedding similarity, with each parent chunk further split into character-based leaf chunks, preserving the two-level parent/child chunk tree used across the retrieval pipeline.

## Requirements

### Requirement: Semantic chunking by embedding similarity
The system SHALL support a `semantic` chunking strategy that splits document text into semantic units: the text is first split into sentences, each sentence is embedded via the configured embedding provider, adjacent sentence similarity is computed, and sentence groups whose boundaries show a similarity drop below a configured threshold form parent chunks, with a target parent size of about 2000 characters. The `semantic` strategy SHALL be available for every supported file type (pdf, markdown, docx, excel, text, csv) regardless of structural signals.

#### Scenario: Adjacent sentences with low similarity start a new chunk
- **WHEN** a document is chunked with the `semantic` strategy and two adjacent sentences have a cosine similarity below the threshold
- **THEN** the second sentence starts a new parent chunk while both chunks remain within the target size

#### Scenario: Parent chunk size is bounded
- **WHEN** accumulating sentences into a semantic parent chunk would exceed the target size
- **THEN** the chunk is closed at the accumulated sentences and a new parent chunk starts, so no parent chunk exceeds the target size

#### Scenario: Semantic chunking works without structural signals
- **WHEN** a file type without heading structure (e.g. pdf, txt) is chunked with the `semantic` strategy
- **THEN** the system produces semantic parent chunks with `chapter_title` unset, instead of rejecting the combination

### Requirement: Two-level tree is preserved under semantic chunking
Semantic parent chunks SHALL be produced at level 1 and SHALL be further split into level 0 leaf chunks by the same character-based recursive splitter used by other strategies, with parent/child references and `chunk_index` assigned as in the standard chunk tree.

#### Scenario: Semantic parent yields character leaf chunks
- **WHEN** a semantic parent chunk is split
- **THEN** each leaf chunk references its parent chunk, carries the semantic parent's `chapter_title`, and all leaves are the retrieval units destined for the vector store

### Requirement: Embedding failure degrades to character chunking
When the embedding provider is unreachable, times out, or raises during semantic chunking, the system SHALL fall back to the `char` strategy for that document, log a warning, and record the effective strategy (`char`) in the document metadata, so ingestion completes without interruption.

#### Scenario: Embedding service down during upload
- **WHEN** a document is uploaded with the `semantic` strategy and embedding calls fail
- **THEN** the document is chunked with character-based chunking, the effective strategy recorded in metadata is `char`, and a warning is logged
