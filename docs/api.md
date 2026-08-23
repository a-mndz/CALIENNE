# calienne API Reference

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python tools/generate_api_reference.py -->

Generated from the live FastAPI OpenAPI schema (`app.openapi()` in
`server.py`). Run `python tools/generate_api_reference.py` after changing
routes; CI fails if this file is stale.

**Title:** Calienne  
**Version:** 1.0.0

## `GET /`

Serve Index

Serve the main HTML page.

**Responses:**

- `200` Successful Response

## `POST /api/checkpoints/{checkpoint_id}/restore`

Restore Checkpoint

Resume pipeline from a checkpoint.

**Parameters:**

- `checkpoint_id` (path) (required): `string`

**Request body:** `CheckpointRestoreRequest`

**Responses:**

- `200` Successful Response — `CheckpointRestoreResponse`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/checkpoints/{request_id}`

List Checkpoints

List checkpoints for a request.

**Parameters:**

- `request_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `CheckpointListResponse`
- `422` Validation Error — `HTTPValidationError`

## `DELETE /api/checkpoints/{request_id}`

Delete Checkpoints

Delete all checkpoints for a request.

**Parameters:**

- `request_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `CheckpointDeleteResponse`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/config`

Get Config

Return non-sensitive configuration.

**Responses:**

- `200` Successful Response — `object`

## `GET /api/config/vault`

Get Vault Status

Return secure masked status of provider API keys in vault.

Admin-only like the write path: even masked key status (configured flag,
last 4 chars) describes the server's secrets, not the caller's own data.

**Responses:**

- `200` Successful Response — `object`

## `POST /api/config/vault`

Save Vault Secret

Save an API key securely into OS Keyring and running memory enclave.

**Request body:** `VaultSaveRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/conversations`

Get Conversations

Return all conversation sessions owned by the current user from PostgreSQL.

**Responses:**

- `200` Successful Response — `object`

## `POST /api/conversations`

Save Conversation

Persist or update a conversation session and its transcript in PostgreSQL.

**Request body:** `ConversationSaveRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `DELETE /api/conversations`

Purge Conversations

Delete every conversation owned by the current user.

GDPR Art. 17 erasure path for durable memory: sessions cascade to their
messages (ON DELETE CASCADE), and the memory-search index is a GENERATED
column over those messages, so nothing user-authored survives this call.

**Responses:**

- `200` Successful Response — `object`

## `DELETE /api/conversations/{session_id}`

Delete Conversation

Delete a conversation owned by current user from PostgreSQL.

**Parameters:**

- `session_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/debug/replay/{trace_id}`

Get Replay Trace

Return a recorded execution trace for offline replay/debugging.

Gated by ``CALIENNE_ENABLE_REPLAY`` — when the flag is off the
``replay_store`` component is ``None`` and this reports 503 rather
than fabricating an empty trace (ADR-007).

**Parameters:**

- `trace_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/models`

Get Models

Return active models configured in the orchestrator strategy.

**Responses:**

- `200` Successful Response — `object`

## `POST /api/models/add`

Add Model Endpoint

Dynamically register a new model in the active strategy and pool.

**Request body:** `ModelAddRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/models/chain`

Update Model Chain Endpoint

Update the priority order / fallback chain of models for a role.

**Request body:** `ModelChainUpdateRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/models/custom`

Register Custom Model

Register a custom model and optional gateway URL in orchestrator.

**Request body:** `CustomModelRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/models/delete`

Delete Model Endpoint

Remove a model from the active orchestrator strategy.

**Request body:** `ModelDeleteRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/models/primary`

Set Primary Model Endpoint

Designate a model as the Primary model for a role (e.g. Primary Judge).

**Request body:** `ModelPrimaryUpdateRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/models/roles`

Update Model Roles Endpoint

Update role assignments (e.g. Judge, Generation, Breaker) for any model.

**Request body:** `ModelRolesUpdateRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/models/toggle`

Toggle Model Endpoint

Enable or disable a model provider in the active pool.

**Request body:** `ModelToggleRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/providers`

List Providers Endpoint

List all custom providers with secure masked status and model counts.

**Responses:**

- `200` Successful Response — `object`

## `POST /api/providers`

Save Provider Endpoint

Register or update a custom provider, saving key securely in OS Keyring.

**Request body:** `ProviderSaveRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/providers/discover`

Discover Provider Models

Probe model provider endpoint to automatically fetch available models.

**Request body:** `ProviderDiscoverRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/providers/health`

Get Providers Health

Return health metrics for all registered providers.

**Responses:**

- `200` Successful Response — array of `ProviderHealthResponse`

## `DELETE /api/providers/{provider_id}`

Delete Provider Endpoint

Delete a custom provider and purge its secrets from OS Keyring.

**Parameters:**

- `provider_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/providers/{provider_name}/recovery`

Trigger Provider Recovery

Manually trigger recovery for a DEAD provider (admin only — MED-023).

**Parameters:**

- `provider_name` (path) (required): `string`

**Request body:** `ProviderRecoveryRequest`

**Responses:**

- `200` Successful Response — `ProviderRecoveryResponse`
- `422` Validation Error — `HTTPValidationError`

## `POST /api/query`

Handle Query

Run the micro-mode pipeline for a user query.

**Request body:** `QueryRequest`

**Responses:**

- `200` Successful Response
- `422` Validation Error — `HTTPValidationError`

## `POST /api/query/stream`

Handle Query Stream

Stream the micro-mode pipeline as Server-Sent Events.

Each event is a JSON-encoded SSE data line.  The frontend reads the
response via ``fetch()`` + ``ReadableStream`` and updates the UI in
real time as each pipeline stage completes.

**Request body:** `QueryRequest`

**Responses:**

- `200` Successful Response
- `422` Validation Error — `HTTPValidationError`

## `POST /api/sessions`

Create Session

Create a new conversation session owned by the caller (HIGH-015).

**Request body:** `SessionCreateRequest`

**Responses:**

- `201` Successful Response — `SessionCreateResponse`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/sessions/{session_id}`

Get Session Metadata

Retrieve session metadata (HIGH-015 ownership enforced).

**Parameters:**

- `session_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `SessionMetadataResponse`
- `422` Validation Error — `HTTPValidationError`

## `DELETE /api/sessions/{session_id}`

Close Session

Explicitly close a conversation session (HIGH-015 ownership enforced).

**Parameters:**

- `session_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `SessionCloseResponse`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/sessions/{session_id}/history`

Get Session History

Retrieve conversation history (HIGH-015 ownership enforced).

**Parameters:**

- `session_id` (path) (required): `string`

**Responses:**

- `200` Successful Response — `SessionHistoryResponse`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/status`

Get Status

Return provider health, dynamic models, and session telemetry.

**Responses:**

- `200` Successful Response — `object`

## `POST /api/strategy/mode`

Set Strategy Mode Endpoint

Switch the orchestrator strategy mode (FREE, HYBRID, PAID).

**Request body:** `StrategyModeRequest`

**Responses:**

- `200` Successful Response — `object`
- `422` Validation Error — `HTTPValidationError`

## `GET /api/telemetry`

Get Telemetry

Return session telemetry metrics.

**Responses:**

- `200` Successful Response — `object`

## `POST /auth/login`

Login User

Authenticate credentials and emit an httpOnly JWT cookie.

**Request body:** `AuthLoginRequest`

**Responses:**

- `200` Successful Response
- `422` Validation Error — `HTTPValidationError`

## `POST /auth/logout`

Logout User

Clear the httpOnly auth cookie (HIGH-013).

**Responses:**

- `200` Successful Response

## `POST /auth/refresh`

Refresh Token

Refresh the authenticated user's httpOnly JWT cookie.

**Responses:**

- `200` Successful Response

## `POST /auth/register`

Register User

Register a new user, checking if the email already exists.

**Request body:** `AuthRegisterRequest`

**Responses:**

- `201` Successful Response
- `422` Validation Error — `HTTPValidationError`

## `GET /calienne_hero_video_graded.mp4`

Serve Login Hero Video

Serve the login HTML hero video.

**Responses:**

- `200` Successful Response

## `GET /login`

Serve Login

Serve the login HTML page.

**Responses:**

- `200` Successful Response

## `GET /metrics`

Prometheus Metrics

Prometheus text exposition of decision and provider-health metrics.

Auth: a scraper cannot present the httpOnly JWT cookie the admin endpoints
rely on, so this path uses its own bearer token (``CALIENNE_METRICS_TOKEN``).
In production the token is mandatory — an unset token means the endpoint
refuses to serve rather than silently exposing internals. Outside production
an unset token leaves it open so local scraping needs no setup.

**Responses:**

- `200` Successful Response

## `GET /{full_path}`

Catch All

Catch-all route for SPA client-side routing.

**Parameters:**

- `full_path` (path) (required): `string`

**Responses:**

- `200` Successful Response
- `422` Validation Error — `HTTPValidationError`
