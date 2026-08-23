"""CALIENNE orchestrator package.

Keep package imports lazy so lightweight modules such as
``orchestrator.contracts`` can be imported without pulling the full runtime
graph into module initialization.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "ConversationDirector": ("orchestrator.conversation", "ConversationDirector"),
    "ConversationSession": ("orchestrator.conversation", "ConversationSession"),
    "ConversationState": ("orchestrator.conversation", "ConversationState"),
    "ConversationTurn": ("orchestrator.conversation", "ConversationTurn"),
    "InvalidConversationTransitionError": ("orchestrator.conversation", "InvalidConversationTransitionError"),
    "Checkpoint": ("orchestrator.checkpoints", "Checkpoint"),
    "CheckpointManager": ("orchestrator.checkpoints", "CheckpointManager"),
    "arbitrate_and_synthesize": ("orchestrator.evaluation", "arbitrate_and_synthesize"),
    "EpistemicMemory": ("orchestrator.memory", "EpistemicMemory"),
    "epistemic_memory": ("orchestrator.memory", "epistemic_memory"),
    "NodeType": ("orchestrator.reasoning_graph", "NodeType"),
    "EdgeType": ("orchestrator.reasoning_graph", "EdgeType"),
    "GraphNode": ("orchestrator.reasoning_graph", "GraphNode"),
    "GraphEdge": ("orchestrator.reasoning_graph", "GraphEdge"),
    "ReasoningGraph": ("orchestrator.reasoning_graph", "ReasoningGraph"),
    "MemoryManager": ("orchestrator.memory_manager", "MemoryManager"),
    "SummarizationStrategy": ("orchestrator.memory_manager", "SummarizationStrategy"),
    "InsufficientCapacityError": ("orchestrator.memory_manager", "InsufficientCapacityError"),
    "run_micro_mode": ("orchestrator.pipelines", "run_micro_mode"),
    "MicroModeResult": ("orchestrator.pipelines", "MicroModeResult"),
    "PipelineState": ("orchestrator.state_machine", "PipelineState"),
    "StateMachine": ("orchestrator.state_machine", "StateMachine"),
    "StateTransition": ("orchestrator.state_machine", "StateTransition"),
    "InvalidTransitionError": ("orchestrator.state_machine", "InvalidTransitionError"),
    "ClaimManager": ("orchestrator.claims", "ClaimManager"),
    "Claim": ("orchestrator.claims", "Claim"),
    "ClaimType": ("orchestrator.claims", "ClaimType"),
    "ValidationStatus": ("orchestrator.claims", "ValidationStatus"),
    "DecisionEngine": ("orchestrator.decisions", "DecisionEngine"),
    "DecisionMetrics": ("orchestrator.decisions", "DecisionMetrics"),
    "DecisionStrategy": ("orchestrator.decisions", "DecisionStrategy"),
    "EventType": ("orchestrator.streaming", "EventType"),
    "StreamEvent": ("orchestrator.streaming", "StreamEvent"),
    "StreamingManager": ("orchestrator.streaming", "StreamingManager"),
    "initialize_calienne_components": ("orchestrator.calienne_orchestrator", "initialize_calienne_components"),  # noqa: E501
    "create_request_passport": ("orchestrator.calienne_orchestrator", "create_request_passport"),
    "create_request_state_machine": ("orchestrator.calienne_orchestrator", "create_request_state_machine"),
    "ExecutionManager": ("orchestrator.execution_manager", "ExecutionManager"),
    "StrategicPlanner": ("orchestrator.strategic_planner", "StrategicPlanner"),
    "ExecutionPlanner": ("orchestrator.execution_planner", "ExecutionPlanner"),
    "Scheduler": ("orchestrator.scheduler", "Scheduler"),
    "run_dag_blocking": ("orchestrator.scheduler", "run_dag_blocking"),
    "TokenBudgetManager": ("orchestrator.budget", "TokenBudgetManager"),
    "PredictionLayer": ("orchestrator.prediction", "PredictionLayer"),
    "ContextManager": ("orchestrator.context_manager", "ContextManager"),
    "SkillComposer": ("orchestrator.skills", "SkillComposer"),
    "SkillDefinition": ("orchestrator.skills", "SkillDefinition"),
    "MetaReasoner": ("orchestrator.meta_reasoner", "MetaReasoner"),
    "EarlyExitDecision": ("orchestrator.meta_reasoner", "EarlyExitDecision"),
    "UncertaintyEngine": ("orchestrator.uncertainty", "UncertaintyEngine"),
    "UncertaintyDecision": ("orchestrator.uncertainty", "UncertaintyDecision"),
    "RetrievalService": ("orchestrator.retrieval", "RetrievalService"),
    "RetrievalRequest": ("orchestrator.retrieval", "RetrievalRequest"),
    "RetrievalResult": ("orchestrator.retrieval", "RetrievalResult"),
    "SourceCandidate": ("orchestrator.retrieval", "SourceCandidate"),
    "RetrievalProvider": ("orchestrator.retrieval", "RetrievalProvider"),
    "InMemoryRetrievalProvider": ("orchestrator.retrieval", "InMemoryRetrievalProvider"),
    "DeterministicRetrievalProvider": ("orchestrator.retrieval", "DeterministicRetrievalProvider"),
    "StaticOverrideProvider": ("orchestrator.retrieval", "StaticOverrideProvider"),
    "load_routing_weights": ("orchestrator.retrieval", "load_routing_weights"),
    "load_route_gating": ("orchestrator.retrieval", "load_route_gating"),
    "rank_sources": ("orchestrator.retrieval", "rank_sources"),
    "score_candidate": ("orchestrator.retrieval", "score_candidate"),
    "should_retrieve": ("orchestrator.retrieval", "should_retrieve"),
    "KnowledgeFact": ("orchestrator.knowledge_layer", "KnowledgeFact"),
    "KnowledgeBundle": ("orchestrator.knowledge_layer", "KnowledgeBundle"),
    "KnowledgeLayer": ("orchestrator.knowledge_layer", "KnowledgeLayer"),
    "ReasoningLayer": ("orchestrator.reasoning_layer", "ReasoningLayer"),
    "ValidationLayer": ("orchestrator.validation_layer", "ValidationLayer"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
