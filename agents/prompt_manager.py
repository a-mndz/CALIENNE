import logging
import os
import re
import threading
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any, Optional, Tuple

logger = logging.getLogger("calienne.Agents.PromptManager")


def clean_xml_prompt(content: str) -> str:
    """
    Strips leading and trailing markdown code block fences (e.g. ```xml and ```)
    to ensure the model receives clean XML.
    """
    content = content.strip()
    if content.startswith("```xml"):
        content = content[6:].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    return content.strip()


def validate_xml(content: str) -> Tuple[bool, Optional[str]]:
    """
    Validate XML syntax using ElementTree parser.

    Args:
        content: XML content string to validate

    Returns:
        Tuple of (is_valid, error_message).
        - (True, None) if valid XML
        - (False, error_message) if invalid with parsing failure details
    """
    if not content or not content.strip():
        return False, "Empty XML content"

    try:
        ET.fromstring(content)
        return True, None
    except ET.ParseError as e:
        error_msg = f"XML parsing error: {str(e)}"
        return False, error_msg


def load_prompt_file(filepath: str) -> str:
    """
    Loads and cleans an XML prompt file from the filesystem.
    Handles filesystem errors with specific error types.

    Args:
        filepath: Path to the XML prompt file

    Returns:
        Cleaned XML content or empty string on error
    """
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = clean_xml_prompt(f.read())
                return content
        else:
            logger.warning(f"File not found: {filepath}")
            return ""
    except PermissionError:
        logger.error(f"Permission denied: {filepath}")
        return ""
    except IOError as e:
        logger.error(f"I/O error loading {filepath}: {e}")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error loading {filepath}: {e}")
        return ""


def load_prompt_file_with_validation(filepath: str) -> str:
    """
    Loads, cleans, and validates an XML prompt file from the filesystem.
    Returns empty string if file is missing, has errors, or contains invalid XML.

    Args:
        filepath: Path to the XML prompt file

    Returns:
        Validated XML content or empty string on error
    """
    filename = os.path.basename(filepath)
    content = load_prompt_file(filepath)

    if not content:
        return ""

    is_valid, error_msg = validate_xml(content)
    if not is_valid:
        logger.error(f"Invalid XML in {filename}: {error_msg}")
        return ""

    return content


def load_runtime_contracts(prompts_dir: Optional[str] = None) -> list:
    """
    Load the runtime contract XML files from prompts/runtime/ that shape a
    single completion call's OUTPUT, sorted by numeric prefix.

    HIGH-018 audit finding: 48 file I/O ops per request (20-80ms).  This
    function memoises its result so subsequent calls within the same process
    cost a dictionary lookup.  An optional ``clear_prompt_cache`` helper is
    exposed for SIGHUP / tests that need to wipe state.

    Live-capture finding (2026-08-22): shipping all 12 contracts put every
    request body at ~30KB, which Groq hard-rejects (HTTP 413) — so the
    per-call layer is restricted to the contracts a completion call can
    actually act on. The pipeline-mechanics contracts (prompt loader,
    context manager, execution/pipeline state, memory manager, stream
    transport, provider behaviour) describe orchestration the model cannot
    affect from inside one completion; they remain in prompts/runtime/ for
    the components that consume them directly.
    """
    return list(_load_runtime_contracts_cached(prompts_dir))


# Output-shaping contracts included in every per-call system prompt.
PER_CALL_RUNTIME_CONTRACTS: frozenset[str] = frozenset(
    {
        "02_response_contract.xml",   # JSON response format
        "05_error_handling.xml",      # failure semantics of the answer itself
        "10_security_contract.xml",   # untrusted-input handling rules
    }
)


@lru_cache(maxsize=4)
def _load_runtime_contracts_cached(prompts_dir: Optional[str]) -> tuple:
    """Internal cache wrapper; returns an immutable tuple to be cache-friendly."""
    if prompts_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompts_dir = os.path.join(base_dir, "prompts")

    runtime_dir = os.path.join(prompts_dir, "runtime")
    runtime_prompts: list[str] = []

    if not os.path.exists(runtime_dir):
        logger.warning(f"Runtime prompts directory not found: {runtime_dir}")
        return tuple(runtime_prompts)

    try:
        xml_files = sorted(
            f
            for f in os.listdir(runtime_dir)
            if f.endswith(".xml") and f in PER_CALL_RUNTIME_CONTRACTS
        )
        for filename in xml_files:
            filepath = os.path.join(runtime_dir, filename)
            content = load_prompt_file_with_validation(filepath)
            if content.strip():
                runtime_prompts.append(content)
    except PermissionError:
        logger.error(f"Permission denied accessing directory: {runtime_dir}")
    except OSError as e:
        logger.error(f"I/O error reading directory {runtime_dir}: {e}")

    return tuple(runtime_prompts)


_CACHE_LOCK = threading.Lock()


def clear_prompt_cache() -> None:
    """Drop cached prompt fragments.  Used for SIGHUP reload and in tests."""
    with _CACHE_LOCK:
        _load_runtime_contracts_cached.cache_clear()


def load_system_prompt(filename: str, prompts_dir: Optional[str] = None) -> str:
    """
    Load a specific system prompt XML file with validation and fallback.

    Args:
        filename: Name of the system prompt file (e.g., "05_logician.xml")
        prompts_dir: Optional base prompts directory path. If None, uses default.

    Returns:
        Validated XML content, or fallback persona content, or empty string
    """
    if prompts_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompts_dir = os.path.join(base_dir, "prompts")

    filepath = os.path.join(prompts_dir, "system", filename)
    content = load_prompt_file_with_validation(filepath)

    if content:
        return content

    logger.warning(f"Falling back to persona constants for: {filename}")
    from agents.personas import PERSONA_REGISTRY

    base_name = os.path.basename(filename)
    parts = base_name.replace(".xml", "").split("_")
    persona_key = parts[-1].lower() if parts else ""

    fallback = PERSONA_REGISTRY.get(persona_key, "")
    if not fallback:
        logger.error(f"Persona key '{persona_key}' not found in PERSONA_REGISTRY")

    return fallback


def get_load_order_verification(prompts_dir: Optional[str] = None) -> dict[str, Any]:
    """
    Verify the prompt assembly hierarchy and return a structured report.

    Args:
        prompts_dir: Optional base prompts directory path. If None, uses default.

    Returns:
        Dictionary with verification report:
        - hierarchy_valid (bool): Whether the hierarchy is valid
        - missing_files (list): List of missing required files
        - load_order (list): Expected load order of runtime contracts
        - errors (list): List of errors encountered during verification
    """
    if prompts_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompts_dir = os.path.join(base_dir, "prompts")

    report = {
        "hierarchy_valid": True,
        "missing_files": [],
        "load_order": [],
        "errors": []
    }

    # Expected runtime contracts (00-11)
    expected_runtime = [
        "00_agent_runtime.xml",
        "01_prompt_loader.xml",
        "02_response_contract.xml",
        "03_context_manager.xml",
        "04_execution_contract.xml",
        "05_error_handling.xml",
        "06_pipeline_state.xml",
        "07_memory_manager.xml",
        "08_stream_contract.xml",
        "09_provider_contract.xml",
        "10_security_contract.xml",
        "11_completion_contract.xml"
    ]

    # Verify directory structure
    runtime_dir = os.path.join(prompts_dir, "runtime")
    system_dir = os.path.join(prompts_dir, "system")

    if not os.path.exists(prompts_dir):
        report["hierarchy_valid"] = False
        report["errors"].append(f"Prompts directory not found: {prompts_dir}")
        logger.error(f"Verification failed: Prompts directory not found: {prompts_dir}")
        return report

    if not os.path.exists(runtime_dir):
        report["hierarchy_valid"] = False
        report["errors"].append(f"Runtime prompts directory not found: {runtime_dir}")
        logger.error(f"Verification failed: Runtime directory not found: {runtime_dir}")
        return report

    if not os.path.exists(system_dir):
        report["hierarchy_valid"] = False
        report["errors"].append(f"System prompts directory not found: {system_dir}")
        logger.error(f"Verification failed: System directory not found: {system_dir}")
        return report

    # Check runtime contracts (00-11)
    for filename in expected_runtime:
        filepath = os.path.join(runtime_dir, filename)
        if not os.path.exists(filepath):
            report["missing_files"].append(f"runtime/{filename}")
            report["hierarchy_valid"] = False
        else:
            # Validate XML
            content = load_prompt_file(filepath)
            if content:
                is_valid, error_msg = validate_xml(content)
                if not is_valid:
                    report["errors"].append(f"Invalid XML in {filename}: {error_msg}")
                    report["hierarchy_valid"] = False

    # Build expected load order
    report["load_order"] = [
        "role_block",
        *[f"runtime/{f}" for f in expected_runtime],
        "system_prompt"
    ]

    # Log verification results
    if report["hierarchy_valid"]:
        logger.info("Prompt hierarchy verification PASSED")
    else:
        logger.warning(
            f"Prompt hierarchy verification FAILED: "
            f"{len(report['missing_files'])} missing files, "
            f"{len(report['errors'])} errors"
        )

    return report


def assemble_agent_prompt(
    role: str,
    pipeline_stage: str,
    objective: str,
    iteration: int,
    execution_mode: str,
    system_prompt_filename: str,
    prompts_dir: Optional[str] = None,
) -> str:
    """
    Assembles the hierarchical calienne prompt layout with dynamic role injection:

    1. <ROLE> block
    2. Runtime contracts (00-11) sorted by numeric prefix
    3. Agent-specific system prompt

    Args:
        role: Current agent role name
        pipeline_stage: Current pipeline stage
        objective: Current objective
        iteration: Current iteration number
        execution_mode: Current execution mode
        system_prompt_filename: Name of the system prompt XML file
        prompts_dir: Optional base prompts directory path

    Returns:
        Assembled prompt string
    """
    # 1. Build the <ROLE> block
    role_block = f"""<ROLE>

Current Role

{role}

Current Pipeline Stage

{pipeline_stage}

Current Objective

{objective}

Current Iteration

{iteration}

Execution Mode

{execution_mode}

</ROLE>"""

    # 2. Load all runtime XMLs dynamically, sorted by prefix
    runtime_prompts = load_runtime_contracts(prompts_dir)

    # 3. Load agent-specific XML prompt with fallback
    agent_prompt = load_system_prompt(system_prompt_filename, prompts_dir)

    # Combine all parts with double newlines. Static content (runtime
    # contracts + agent prompt) MUST precede the per-request <ROLE> block:
    # provider prompt caches (OpenAI, Gemini implicit, DeepSeek, Groq gpt-oss)
    # match on longest common prefix, and a volatile block first would
    # invalidate the whole ~25k-token static prefix on every request.
    parts = runtime_prompts + [agent_prompt, role_block]
    non_empty_parts = [p for p in parts if p.strip()]
    return "\n\n".join(non_empty_parts)
