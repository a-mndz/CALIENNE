"""
Shared validation utilities for CALIENNE components.

This module provides common validation patterns extracted from
duplicate code across the codebase, including:
- Non-empty string validation
- Non-negative integer validation
- List/dict type and length validation
- Enum string validation
- Range validation
- UUID validation
- Confidence label-to-float conversion
- datetime timezone utilities
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

# ── datetime Utilities ──────────────────────────────────────────────────


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp.

    This replaces the duplicate utc_now() definitions in passport.py,
    conversation.py, checkpoints.py, and reasoning_graph.py.
    """
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC.

    Parameters
    ----------
    value:
        The datetime to normalize.

    Returns
    -------
    Timezone-aware datetime in UTC.

    Raises
    ------
    TypeError: If value is not a datetime.
    """
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    """Serialize a datetime in ISO 8601 UTC form.

    Parameters
    ----------
    value:
        The datetime to serialize.

    Returns
    -------
    ISO 8601 formatted string with UTC timezone.
    """
    return as_utc(value).isoformat()


# ── String Validation ───────────────────────────────────────────────────


def validate_non_empty(value: Any, field_name: str, *, strip: bool = True) -> str:
    """Validate that a value is a non-empty string.

    This replaces the 19+ duplicate validation blocks across passport.py,
    conversation.py, and checkpoints.py.

    Parameters
    ----------
    value:
        The value to validate.
    field_name:
        Name of the field for error messages.
    strip:
        Whether to strip whitespace before checking (default True).

    Returns
    -------
    The stripped string value.

    Raises
    ------
    ValueError: If value is not a non-empty string.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    if strip:
        value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def validate_string_optional(value: Any, field_name: str) -> Optional[str]:
    """Validate that a value is a string or None.

    Parameters
    ----------
    value:
        The value to validate.
    field_name:
        Name of the field for error messages.

    Returns
    -------
    The string value or None.

    Raises
    ------
    TypeError: If value is not a string or None.
    """
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    return value


# ── Integer Validation ──────────────────────────────────────────────────


def validate_non_negative_int(value: Any, field_name: str) -> int:
    """Validate that a value is a non-negative integer.

    This replaces the 4 duplicate validation blocks in passport.py and conversation.py.

    Parameters
    ----------
    value:
        The value to validate.
    field_name:
        Name of the field for error messages.

    Returns
    -------
    The integer value.

    Raises
    ------
    ValueError: If value is not a non-negative integer.
    """
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def validate_range(
    value: Any,
    min_val: float,
    max_val: float,
    field_name: str,
    *,
    inclusive: bool = True,
) -> float:
    """Validate that a numeric value is within a range.

    Parameters
    ----------
    value:
        The value to validate.
    min_val:
        Minimum allowed value.
    max_val:
        Maximum allowed value.
    field_name:
        Name of the field for error messages.
    inclusive:
        Whether the range bounds are inclusive (default True).

    Returns
    -------
    The numeric value as float.

    Raises
    ------
    TypeError: If value is not numeric.
    ValueError: If value is out of range.
    """
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a number")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if inclusive:
        if value < min_val or value > max_val:
            raise ValueError(
                f"{field_name} must be between {min_val} and {max_val}, got {value}"
            )
    else:
        if value <= min_val or value >= max_val:
            raise ValueError(
                f"{field_name} must be between {min_val} and {max_val} (exclusive), got {value}"
            )
    return float(value)


def validate_positive_int(value: Any, field_name: str) -> int:
    """Validate that a value is a positive integer (> 0).

    Parameters
    ----------
    value:
        The value to validate.
    field_name:
        Name of the field for error messages.

    Returns
    -------
    The integer value.

    Raises
    ------
    ValueError: If value is not a positive integer.
    """
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


# ── List/Dict Validation ────────────────────────────────────────────────


def validate_list(
    value: Any,
    field_name: str,
    *,
    max_length: int | None = None,
    element_type: type | None = None,
    element_type_name: str = "entries",
) -> list:
    """Validate that a value is a list with optional length and element type checks.

    This replaces the 7+ duplicate list validation blocks in passport.py.

    Parameters
    ----------
    value:
        The value to validate.
    field_name:
        Name of the field for error messages.
    max_length:
        Maximum allowed length (None for no limit).
    element_type:
        Required type for all elements (None for no type check).
    element_type_name:
        Name of the element type for error messages.

    Returns
    -------
    The list value.

    Raises
    ------
    TypeError: If value is not a list or elements have wrong type.
    ValueError: If list exceeds max_length.
    """
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{field_name} cannot contain more than {max_length} entries")
    if element_type is not None:
        if any(not isinstance(entry, element_type) for entry in value):
            raise TypeError(f"{field_name} {element_type_name} must be {element_type.__name__}")
    return value


def validate_string_list(value: list, field_name: str) -> list[str]:
    """Validate that all elements in a list are strings.

    Parameters
    ----------
    value:
        The list to validate.
    field_name:
        Name of the field for error messages.

    Returns
    -------
    The list of strings.

    Raises
    ------
    TypeError: If any element is not a string.
    """
    return validate_list(value, field_name, element_type=str, element_type_name="entries")


def validate_dict(value: Any, field_name: str) -> dict:
    """Validate that a value is a dictionary.

    Parameters
    ----------
    value:
        The value to validate.
    field_name:
        Name of the field for error messages.

    Returns
    -------
    The dictionary value.

    Raises
    ------
    TypeError: If value is not a dictionary.
    """
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dictionary")
    return value


# ── Enum Validation ─────────────────────────────────────────────────────


def validate_enum(
    value: Any,
    enum_class: type | set | tuple | list,
    field_name: str,
) -> Any:
    """Validate that a value is a valid enum member or member of an allowed set.

    This replaces the 3+ duplicate enum validation blocks across the codebase.

    Parameters
    ----------
    value:
        The value to validate.
    enum_class:
        An Enum class, or a set/tuple/list of allowed values.
    field_name:
        Name of the field for error messages.

    Returns
    -------
    The validated value (or enum member).

    Raises
    ------
    ValueError: If value is not in the enum or allowed set.
    """
    if isinstance(enum_class, type) and issubclass(enum_class, Enum):
        allowed_values = [e.value for e in enum_class]
        if isinstance(value, enum_class):
            return value
        if value not in allowed_values:
            raise ValueError(
                f"Invalid {field_name}: {value}. Must be one of: {allowed_values}"
            )
        return value
    else:
        # Treat as set/tuple/list of allowed values
        allowed = set(enum_class)
        if value not in allowed:
            raise ValueError(
                f"Invalid {field_name}: {value}. Must be one of: {allowed}"
            )
        return value


# ── UUID Validation ─────────────────────────────────────────────────────


def validate_uuid(value: Any, field_name: str, *, version: int | None = None) -> str:
    """Validate that a value is a valid UUID string.

    Parameters
    ----------
    value:
        The value to validate (should be a UUID string).
    field_name:
        Name of the field for error messages.
    version:
        Required UUID version (None for any version).

    Returns
    -------
    The UUID string.

    Raises
    ------
    ValueError: If value is not a valid UUID or wrong version.
    """
    import uuid as uuid_mod

    try:
        parsed = uuid_mod.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc
    if version is not None and parsed.version != version:
        raise ValueError(f"{field_name} must be a UUID v{version}")
    return str(parsed)


# ── Confidence Label Conversion ─────────────────────────────────────────


# Mapping from confidence labels to float values
CONFIDENCE_TO_FLOAT: dict[str, float] = {
    "high": 0.9,
    "medium": 0.5,
    "low": 0.2,
}

# Mapping from float thresholds to confidence labels
_FLOAT_TO_CONFIDENCE: list[tuple[float, str]] = [
    (0.75, "High"),
    (0.4, "Medium"),
]


def confidence_label_to_float(label: str) -> float:
    """Convert a confidence label string to a float value.

    This replaces the duplicate confidence mapping logic in schemas.py and pipelines.py.

    Parameters
    ----------
    label:
        Confidence label ("high", "medium", "low", or "High", "Medium", "Low").

    Returns
    -------
    Float value (0.0-1.0). Returns 0.5 for unknown labels.
    """
    return CONFIDENCE_TO_FLOAT.get(label.lower().strip(), 0.5)


def float_to_confidence_label(score: float) -> str:
    """Convert a confidence float to a label string.

    Parameters
    ----------
    score:
        Confidence score (0.0-1.0).

    Returns
    -------
    Confidence label ("High", "Medium", or "Low").
    """
    for threshold, label in _FLOAT_TO_CONFIDENCE:
        if score >= threshold:
            return label
    return "Low"


# ── Dictionary Key Resolution ──────────────────────────────────────────


def resolve_field(
    data: dict,
    target: str,
    alternatives: list[str],
    default: Any = None,
) -> None:
    """Resolve a dictionary field from alternative keys with fallback.

    This replaces the duplicate field-mapping logic in schemas.py model_validators.

    Parameters
    ----------
    data:
        The dictionary to resolve from (modified in place).
    target:
        The target key name.
    alternatives:
        List of alternative key names to try.
    default:
        Default value if no key is found.

    Example
    -------
    >>> data = {"answer_text": "Hello"}
    >>> resolve_field(data, "answer", ["answer_text", "response"], default="")
    >>> data["answer"]
    'Hello'
    """
    if target not in data:
        for alt in alternatives:
            if alt in data and data[alt]:
                data[target] = data[alt]
                return
        data[target] = default
