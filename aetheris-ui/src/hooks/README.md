# Custom Hooks for Pipeline and Query Management

This directory contains custom React hooks for managing the calienne UI pipeline execution and query submission.

## usePipelineStages.js

### Overview
Manages the pipeline execution state, tracking agent progress and streaming events from the backend SSE endpoint.

### Key Features
1. **Real-time event processing** - Processes SSE events from backend to update UI state
2. **Progress calculation** - Maps pipeline stages to progress percentages (0-100)
3. **Elapsed time tracking** - Tracks execution time with 100ms precision
4. **Abort functionality** - Allows cancellation of in-progress pipeline execution
5. **Agent state management** - Tracks individual agent states (Breaker, Logician, Creative, Judge)

### API

```javascript
const {
  stage,        // Current pipeline stage: 'idle' | 'breaker' | 'agents' | 'judge' | 'done' | 'error'
  agentStates,  // Per-agent state: { Breaker, Logician, Creative, Judge }
  partialData,  // Partial results for backward compatibility with ReasoningPanel
  progress,     // Progress percentage: 0-100
  elapsedMs,    // Elapsed time in milliseconds since pipeline start
  run,          // Function: (query, history) => Promise<{ data, latencyMs, error, aborted }>
  reset,        // Function: () => void - Resets all state to idle
  abort         // Function: () => void - Aborts current pipeline execution
} = usePipelineStages();
```

### Progress Calculation

The hook maps pipeline stages to progress percentages according to the design specification:

- **Prompt Normalizer**: 0-10% (mapped to 5%)
- **Conversation Director**: 10-20% (mapped to 15%)
- **Breaker**: 20-35% (mapped to 27%)
- **Agents** (Logician + Creative): 35-70% (mapped to 52%)
- **Judge** (Logic + Factual): 70-85% (mapped to 77%)
- **Fusion**: 85-95% (mapped to 90%)
- **Response**: 95-100% (mapped to 97%)
- **Done**: 100%
- **Error/Idle**: 0%

### Event Handling

The hook processes the following SSE event types:

- `agent_started` - Agent begins execution
- `progress` - Agent reports progress update
- `reasoning_summary` - Agent provides reasoning section
- `draft_answer` - Agent provides draft answer
- `agent_completed` - Agent finishes execution
- `error` - Error occurred during execution
- `stage` - Legacy stage event (backward compatibility)

### Elapsed Time Tracking

When the pipeline is running (stage is not 'idle', 'done', or 'error'), the hook:
1. Records the start time when `run()` is called
2. Updates `elapsedMs` every 100ms via `setInterval`
3. Stops updating when pipeline completes or errors

### Abort Functionality

The `abort()` function:
1. Calls `AbortController.abort()` to cancel the fetch request
2. Sets stage to 'error'
3. Resets progress to 0

When starting a new pipeline execution, any in-progress request is automatically aborted.

## useSendQuery.js

### Overview
Manages query submission, conversation history building, and integration with the chat store.

### Key Features
1. **Query submission** - Sends user queries to the backend
2. **Message management** - Creates and updates user/assistant messages in the store
3. **History building** - Builds conversation history for multi-turn context
4. **Error handling** - Gracefully handles various error scenarios
5. **Telemetry tracking** - Records execution metrics for each query

### API

```javascript
const {
  send,         // Function: (conversationId, query) => Promise<void>
  stage,        // Current pipeline stage (from usePipelineStages)
  agentStates,  // Per-agent state (from usePipelineStages)
  partialData,  // Partial results (from usePipelineStages)
  progress,     // Progress percentage (from usePipelineStages)
  elapsedMs,    // Elapsed time in ms (from usePipelineStages)
  abort         // Abort function (from usePipelineStages)
} = useSendQuery();
```

### Send Function

The `send(conversationId, query)` function:

1. **Validates input** - Trims and rejects empty queries
2. **Creates messages** - Adds user message and pending assistant message to store
3. **Builds history** - Constructs conversation history from last 10 messages
4. **Executes pipeline** - Calls `run()` from usePipelineStages
5. **Handles results**:
   - On abort: Returns early without updating
   - On error: Updates assistant message with error status and message
   - On success: Updates assistant message with response data
6. **Records telemetry** - Adds telemetry entry with execution metrics
7. **Resets state** - Calls `reset()` after delay to show final state

### History Building

The hook builds conversation history by:
1. Filtering messages to include only 'user' and completed 'assistant' messages
2. Mapping to simple `{ role, content }` format
3. Filtering out messages with empty content
4. Limiting to last 10 messages to manage context window

### Error Handling

The hook provides user-friendly error messages for:
- **Stream errors**: "Pipeline failed at [stage]: [message]"
- **Network errors**: "Could not reach the calienne backend..."
- **HTTP 500+**: "Backend error (500). The orchestrator failed..."
- **HTTP 422**: "The backend rejected the request payload (422)..."
- **Other errors**: "Request failed with status [code]."

## Testing

Both hooks have comprehensive test coverage (100%):

- **usePipelineStages.test.js**: 15 tests covering progress calculation, event handling, timing, and abort functionality
- **useSendQuery.test.js**: 14 tests covering query submission, history building, error handling, and telemetry

Run tests with:
```bash
npm test -- usePipelineStages.test.js --run
npm test -- useSendQuery.test.js --run
```

## Requirements Satisfied

These hooks satisfy the following requirements from the spec:

- **Requirement 2.4**: Pipeline progress percentage display
- **Requirement 2.5**: Elapsed time display
- **Requirement 5.3**: Real-time pipeline state updates without polling
- **Requirement 5.4**: Agent state updates without page reload
- **Requirement 5.5**: Progress percentage and elapsed time updates

## Usage Example

```javascript
import { useSendQuery } from './hooks/useSendQuery';

function ChatInterface() {
  const { send, stage, progress, elapsedMs, abort } = useSendQuery();
  const [conversationId] = useState('conv-123');

  const handleSubmit = async (query) => {
    await send(conversationId, query);
  };

  const handleAbort = () => {
    abort();
  };

  return (
    <div>
      <div>Stage: {stage}</div>
      <div>Progress: {progress}%</div>
      <div>Elapsed: {elapsedMs}ms</div>
      <button onClick={handleAbort}>Abort</button>
      {/* ... */}
    </div>
  );
}
```
