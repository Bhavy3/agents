from __future__ import annotations

import ast
import operator
import re
from typing import Union

# Collision rejection patterns: dates, phones, IPs, version numbers
_DATE_RE = re.compile(r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
_PHONE_RE = re.compile(r"\b(?:\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b|\b\d{3}-\d{3}-\d{4}\b")
_IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")

# Calculation trigger pattern: optional trigger word followed by math characters
_MATH_TRIGGER_RE = re.compile(
    r"^(?:what(?:'s|\s+is)|\s*calculate|\s*compute|\s*solve)?\s*([0-9\.\s\+\-\*\/\(\)\%]+)\??$",
    re.IGNORECASE,
)

# "X percent of Y" word form: requires the literal "of" so bare "15 % 80" stays modulo
_PERCENT_OF_RE = re.compile(
    r"^(?:what(?:'s|\s+is)\s+|calculate\s+|compute\s+|solve\s+)?"
    r"(\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?)\s+of\s+(\d+(?:\.\d+)?)\s*\??$",
    re.IGNORECASE,
)

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> Union[int, float]:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp):
        op_func = _UNARY_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError("Unsupported unary operator")
        val = _eval_node(node.operand)
        return op_func(val)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        op_func = _OPERATORS.get(op_type)
        if op_func is None:
            raise ValueError(f"Unsupported binary operator: {op_type}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type == ast.Pow:
            if abs(right) > 100 or (abs(left) > 1e10 and right > 1):
                raise ValueError("Exponent or base exceeds safe bounds")
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ZeroDivisionError("Division by zero")
        return op_func(left, right)
    raise ValueError(f"Unsupported AST node: {type(node)}")


def evaluate_arithmetic(text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None

    # Reject non-math structures: dates, phone numbers, IP addresses, software versions
    if _DATE_RE.search(cleaned) or _PHONE_RE.search(cleaned) or _IP_RE.search(cleaned) or _VERSION_RE.search(cleaned):
        return None

    # Reject bitwise XOR / ambiguous power symbol
    if "^" in cleaned:
        return None

    percent_match = _PERCENT_OF_RE.match(cleaned)
    if percent_match:
        percent_value = float(percent_match.group(1))
        base_value = float(percent_match.group(2))
        result = percent_value / 100 * base_value
        formatted = str(int(result)) if result.is_integer() else f"{result:.6g}"
        return f"{percent_match.group(1)}% of {percent_match.group(2)} = {formatted}"

    match = _MATH_TRIGGER_RE.match(cleaned)
    if not match:
        return None

    expr = match.group(1).strip()
    # Require at least one binary operator to constitute a calculation
    if not any(op in expr for op in ("+", "-", "*", "/", "%")):
        return None

    try:
        parsed = ast.parse(expr, mode="eval")
        result = _eval_node(parsed)
    except Exception:
        return None

    if isinstance(result, float) and result.is_integer():
        formatted = str(int(result))
    elif isinstance(result, float):
        formatted = f"{result:.6g}"
    else:
        formatted = str(result)

    return f"{expr} = {formatted}"


def is_explicit_calculation_command(text: str) -> bool:
    cleaned = text.strip().lower()
    if not cleaned:
        return False
    # If it starts with "what is" or "what's", let it stay on the fast-chat path
    if re.match(r"^what(?:'s|\s+is)\b", cleaned):
        return False
    # Matches "calculate ...", "compute ...", "solve ...", or direct formula
    return bool(re.match(r"^(?:calculate|compute|solve)?\s*[0-9\.\s\+\-\*/\(\)%]+\??$", cleaned))


def is_percent_of_question(text: str) -> bool:
    """True for the narrow "X percent of Y" numeric form, which can never be general knowledge."""
    cleaned = text.strip()
    if not cleaned:
        return False
    if _DATE_RE.search(cleaned) or _PHONE_RE.search(cleaned) or _IP_RE.search(cleaned) or _VERSION_RE.search(cleaned):
        return False
    return bool(_PERCENT_OF_RE.match(cleaned))
