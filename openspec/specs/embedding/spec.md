# embedding Specification

## Purpose

Provide a configuration-driven, provider-neutral embedding capability. Business
code obtains a client through a factory and calls one normalized interface;
provider selection, model name, credentials, and provider-specific quirks are
resolved from configuration and hidden inside per-provider adapters.

## Requirements

### Requirement: Configuration-driven provider selection
The system SHALL select the active embedding provider and model exclusively from
environment configuration (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL_NAME`), loaded
through `utils/env.py`. Public embedding methods SHALL NOT accept a `model_name`
argument.

#### Scenario: Provider chosen from config
- **WHEN** `EMBEDDING_PROVIDER=dashscope` is set and a client is requested from
  the factory
- **THEN** a DashScope-backed client instance is returned
- **AND** the model used is `EMBEDDING_MODEL_NAME` without any per-call override

#### Scenario: Unknown provider value
- **WHEN** `EMBEDDING_PROVIDER` is set to a value that is not a member of the
  `EmbeddingProvider` enum
- **THEN** configuration resolution raises a clear error identifying the invalid
  value

### Requirement: Unified embedding interface
All embedding clients SHALL implement a common abstract base class
(`BaseEmbeddingClient`) exposing `embed_documents(docs) -> List[List[float]]` and
`embed_query(query) -> List[float]`, returning pure vectors with no
provider-specific wrapper structures.

#### Scenario: Standardized document embedding
- **WHEN** `embed_documents` is called with one or more texts on any supported
  provider
- **THEN** the return value is a `List[List[float]]` whose order matches the input
  order

#### Scenario: Standardized query embedding
- **WHEN** `embed_query` is called with a single text
- **THEN** the return value is a single `List[float]` vector

### Requirement: Graceful handling of unsupported capabilities
Specialized capabilities (e.g. multimodal embedding) SHALL be defined on the base
class with a default that raises `NotImplementedError` carrying a message naming
the client. Providers that support a capability SHALL override the default.

#### Scenario: Unsupported capability invoked
- **WHEN** `embed_multimodal` is called on a client that does not support it
- **THEN** a `NotImplementedError` is raised indicating the client does not
  support that capability

#### Scenario: Supported capability invoked
- **WHEN** `embed_multimodal` is called on the DashScope client with image or
  video input
- **THEN** the multimodal embedding is produced

### Requirement: Provider registry with factory access
The system SHALL provide an `EmbeddingFactory` that resolves the configured
`EmbeddingProvider` to a client instance from an internal registry. Business code
SHALL obtain clients only through the factory, never by importing a concrete
client.

#### Scenario: Factory returns configured client
- **WHEN** business code calls `EmbeddingFactory.get_client()`
- **THEN** it receives a `BaseEmbeddingClient` instance matching
  `EMBEDDING_PROVIDER`

#### Scenario: Deprecated Cohere remains registered
- **WHEN** the factory registry is inspected
- **THEN** the Cohere client is present and marked deprecated
- **AND** selecting it is possible even though it is not tested

### Requirement: Provider-specific normalization is encapsulated
Each concrete client SHALL normalize its own SDK output to the standardized
return contract, hiding provider quirks (output unwrapping, `text_type`
selection, result ordering) from callers.

#### Scenario: DashScope output normalized and ordered
- **WHEN** the DashScope client embeds a list of documents
- **THEN** it maps documents to `text_type="document"`, sorts results by
  `text_index`, and returns `List[List[float]]` in input order
- **AND** queries are mapped to `text_type="query"` internally without exposing
  `text_type` on the public interface
