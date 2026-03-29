# LiveSync Compatibility Fixes

## Problem

obsidian-self-mcp makes assumptions about LiveSync's CouchDB document format that don't match the actual implementation. This causes data integrity issues on writes and silent failures on reads for certain document types.

## Required LiveSync Settings

These settings MUST be configured for obsidian-self-mcp to function:

| Setting | Required Value | Default | Why |
|---------|---------------|---------|-----|
| `encrypt` | `false` | `true` | No decryption support |
| `usePathObfuscation` | `false` | `true` | No path deobfuscation support |
| `enableCompression` | `false` | `false` | No DEFLATE decompression support |
| `handleFilenameCaseSensitive` | `false` | `false` | Doc IDs are always lowercased |

Compatible with any value (no impact):

| Setting | Notes |
|---------|-------|
| `hashAlg` | We use xxhash64 (LiveSync default). Other algorithms produce different chunk IDs but reads still work. Writes will create chunks with xxhash64 IDs. |
| `chunkSplitterVersion` | We implement V3 Rabin-Karp (LiveSync default). Reads work regardless of splitter. Writes always use Rabin-Karp boundaries. |
| `customChunkSize` | We use 0 (default). Reads work regardless. Writes use default sizing. |
| `useEden` | Deprecated. We write `eden: {}`. Eden chunks in existing docs are not read. |
| `doNotUseFixedRevisionForChunks` | Does not affect our direct CouchDB access. |

Unsupported features:

| Feature | Impact |
|---------|--------|
| End-to-end encryption (E2EE) | All data unreadable |
| Path obfuscation | Cannot find documents |
| Data compression | Chunk data garbled |
| Chunk packs (`chunkpack` type) | Packed chunks not fetched |

## Changes

### 1. Content-hash chunk IDs

**File**: `utils.py`

**Current**: `generate_chunk_id()` returns `h:` + 12 random `[a-z0-9]` chars.

**New**: `generate_chunk_id(content: str) -> str` returns `h:` + xxhash64(content + "-" + utf16_len(content)).toString(base36).

- Add `xxhash` package as a runtime dependency in `pyproject.toml`
- Deterministic: same content always produces the same ID
- Matches LiveSync's default `hashAlg: "xxhash64"` with no passphrase (E2EE disabled)
- LiveSync's hash format: `h:` + hash value in base 36
- LiveSync includes passphrase in hash input when E2EE is enabled; we omit it since we don't support E2EE
- **Important**: LiveSync uses JavaScript's `string.length` (UTF-16 code units) in the hash input, not Unicode code point count. For emoji/supplementary chars, a helper `utf16_len()` must be used to match: characters outside BMP count as 2.

### 2. Rabin-Karp chunk splitting

**New file**: `chunking.py`

Implements LiveSync's V3 Rabin-Karp content-defined chunking with identical parameters:

- PRIME = 31, window size = 48 bytes
- Chunk boundary when `(hash_unsigned) % avgChunkSize == 1`
- Text files: avgChunkSize = max(128, file_size / 20)
- Binary files: avgChunkSize = max(4096, file_size / 12)
- maxChunkSize = min(absoluteMaxPieceSize, avgChunkSize * 5)
- minChunkSize = min(max(avgChunkSize / 4, minimumChunkSize), maxChunkSize)
- absoluteMaxPieceSize = 102400 (100KB, matching LiveSync's `MAX_DOC_SIZE_BIN`)
- UTF-8 safe: does not split in the middle of multi-byte characters
- Remaining bytes after last boundary are yielded as the final chunk

**File**: `client.py`

- `write_note` calls the new splitter for both text and binary content
- Remove `CHUNK_SIZE = 10000` constant
- Binary content: base64 encode first, then split (matching LiveSync behavior)

### 3. Legacy `notes` type support

**File**: `client.py`

- `_get_all_file_docs`: expand type filter from `("plain", "newnote")` to `("plain", "newnote", "notes")`
- Also accept docs without `children` field (legacy `notes` type stores content in `data`)
- `read_note`: if doc type is `"notes"`, read content from `data` field (string or list of strings joined) instead of fetching chunks
- `list_notes`: handle docs that may not have `children` field

### 4. Old chunk cleanup on write

**File**: `client.py`

When `write_note` updates an existing note:

1. Save the old `children` array before overwriting
2. After successfully updating the parent doc, compute orphaned chunks (old children not in new children)
3. Delete orphaned chunks — best-effort with warning logging on failure (same pattern as `delete_note`)

This prevents unbounded CouchDB growth from repeated edits.

### 5. Documentation

**README.md**: New "LiveSync Compatibility" section with:
- Required settings table
- Compatible settings table
- Unsupported features table

**CLAUDE.md**: Update "LiveSync Document Model" section with:
- Required LiveSync settings
- Chunk ID generation method (xxhash64, content-addressed)
- Chunk splitting algorithm (Rabin-Karp V3)

### 6. Tests

**New file**: `tests/test_chunking.py`
- Empty input returns empty list
- Small file (< min chunk size) returns single chunk
- Large text file splits into multiple chunks
- Binary splitting works correctly
- UTF-8 multi-byte boundary safety
- Deterministic: same input always produces same chunks

**Updated**: `tests/test_utils.py`
- `generate_chunk_id` is deterministic (same content -> same ID)
- `generate_chunk_id` has `h:` prefix
- Different content produces different IDs

**Updated**: `tests/test_client.py`
- Write creates multiple chunks for large content
- Write cleans up old chunks on update
- Read handles legacy `notes` type documents

## Dependencies

- Add `xxhash` to `pyproject.toml` runtime dependencies
