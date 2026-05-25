"""SOS-08-C wave-3-f-future remaining (2026-05-24 §15) —
general ECMAScript-subset `<assign expr=...>` parser.

Shared between `transliterate_hdl_sv.py` and `transliterate_hdl_vhdl.py`.

Per the SOS-08-C §15 (2026-05-24) wave-3-f-future-assign amendment,
the chart-author authoring contract for `<assign>` expressions admits
the following subset of ECMA-262 (per `derive` authority relationship —
see §0 boundary declaration):

  * Integer literals — decimal (`42`, `-7`) or hex (`0x2A`).
  * Unary minus applied to an integer literal (`-42`).
  * Datamodel identifier reads — bare identifier resolved against the
    enclosing chart `<datamodel>` (`counter`, `prev`).
  * Binary addition / subtraction (`+`, `-`) between any of the above
    or between two datamodel idents (`counter + 1`, `prev - counter`).
  * Parenthesised sub-expressions for grouping.

NOT supported (rejected with an actionable chart-vocabulary error):

  * Multiplication / division / modulo (`*`, `/`, `%`).
  * Function calls (`f(x)`).
  * Conditional / ternary (`x ? a : b`).
  * String literals (`"abc"`, `'abc'`).
  * Comparison / logical operators (`==`, `<`, `&&`, `||`, `!`).
  * Property access other than the `event.<EV>.value` form handled by
    the upstream `_EVENT_PAYLOAD_RE` regex pre-pass.

The pre-existing event-value form (`event.<EV>.value` /
`event.<EV>.<suffix>`) is matched FIRST by the walkers' regex; this
parser is only invoked when that regex does not match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class AssignExprError(Exception):
    """Parser-side error.  Walkers translate to `UnsupportedChartError`
    with a wave-3-f-future-assign citation + location/expr context."""


@dataclass
class AssignExpr:
    """Result of `_parse_assign_expr`.  Tree shape depends on `kind`.

    Kinds:
      * ``"literal"``       — integer constant in ``value``.
      * ``"ident"``         — datamodel identifier in ``ident``.
      * ``"binop"``         — `+`/`-` operator in ``op`` between
                               ``left`` and ``right`` (both AssignExpr).
      * ``"neg_literal"``   — unary minus on an integer literal; the
                               negated value is in ``value`` (already
                               negative).
      * ``"event_payload"`` — placeholder kind reserved for the
                               event-value path; the walkers handle
                               that via the upstream regex pre-pass
                               and do NOT invoke the parser for it.
                               Included in the dataclass for symmetry
                               so a caller can hold any `<assign>` RHS
                               in one type.
    """

    kind: str
    value: int = 0
    op: str = ""
    left: "AssignExpr | None" = None
    right: "AssignExpr | None" = None
    event_name: str = ""
    ident: str = ""


# ---------------------------------------------------------------------------
# Tokenizer.
# ---------------------------------------------------------------------------


_IDENT_START = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_IDENT_CONT = _IDENT_START | set("0123456789")
_DIGITS = set("0123456789")


def _tokenize(text: str) -> list[tuple[str, str]]:
    """Return a list of (kind, lexeme) tuples.

    Kinds: ``INT`` (decimal or 0x-hex integer), ``IDENT``, ``PLUS``,
    ``MINUS``, ``LPAREN``, ``RPAREN``, ``OTHER`` (any other character —
    surfaces in the parser as a "rejected vocabulary" error with the
    offending lexeme named).
    """
    out: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "+":
            out.append(("PLUS", "+"))
            i += 1
            continue
        if ch == "-":
            out.append(("MINUS", "-"))
            i += 1
            continue
        if ch == "(":
            out.append(("LPAREN", "("))
            i += 1
            continue
        if ch == ")":
            out.append(("RPAREN", ")"))
            i += 1
            continue
        if ch in _DIGITS:
            # Decimal or 0x-hex integer.
            j = i
            if ch == "0" and i + 1 < n and text[i + 1] in ("x", "X"):
                j = i + 2
                while j < n and text[j] in (
                    "0123456789abcdefABCDEF"
                ):
                    j += 1
                if j == i + 2:
                    raise AssignExprError(
                        f"malformed hex literal at offset {i}: '0x' with no digits"
                    )
                out.append(("INT", text[i:j]))
                i = j
                continue
            while j < n and text[j] in _DIGITS:
                j += 1
            out.append(("INT", text[i:j]))
            i = j
            continue
        if ch in _IDENT_START:
            j = i + 1
            while j < n and text[j] in _IDENT_CONT:
                j += 1
            out.append(("IDENT", text[i:j]))
            i = j
            continue
        # Anything else — capture a contiguous run of "OTHER"
        # characters so the parser's error message can name the
        # offending lexeme (e.g. ``*``, ``==``, ``"abc"``).
        if ch in ('"', "'"):
            # String literal — gobble through the matching quote (or
            # to end-of-string if unbalanced) so the error names the
            # full string.
            j = i + 1
            while j < n and text[j] != ch:
                j += 1
            j = min(j + 1, n)
            out.append(("OTHER", text[i:j]))
            i = j
            continue
        j = i + 1
        # Group consecutive symbol chars (e.g. ``==``, ``&&``, ``<=``)
        # for a tidier error message.
        while j < n and not (
            text[j].isspace()
            or text[j] in "+-()0123456789"
            or text[j] in _IDENT_START
        ):
            j += 1
        out.append(("OTHER", text[i:j]))
        i = j
    return out


# ---------------------------------------------------------------------------
# Recursive-descent parser.
# ---------------------------------------------------------------------------
#
# Grammar (the supported subset, RFC 2119 normative — per §15
# 2026-05-24 wave-3-f-future-assign):
#
#   expr        ::= term (('+' | '-') term)*
#   term        ::= unary
#   unary       ::= '-' atom_literal | atom
#   atom        ::= INT | IDENT | '(' expr ')'
#   atom_literal::= INT | '(' expr ')'  -- unary minus permitted only
#                                          on literal at v1 (matches
#                                          §15 normative subset)
#
# Note: at v1 we only accept unary minus on a literal (so ``-42`` is
# legal but ``-counter`` raises).  The grammar's `unary` rule reflects
# this: the parser enters `_parse_unary` and if it sees a leading '-'
# it requires the next atom to be an INT.  Subtraction via binary
# minus (``0 - counter``) remains a legal workaround.


def _parse_assign_expr(
    expr_text: str, datamodel_ids: Iterable[str]
) -> AssignExpr:
    """Parse `expr_text` against the ECMAScript-subset grammar above.

    Returns an `AssignExpr` tree.  Raises `AssignExprError` on any
    rejected form; the walker translates the error to an
    `UnsupportedChartError` with the chart-vocab citation prefix.
    Idents referenced by the expression are validated against
    `datamodel_ids` — unknown idents raise.
    """
    valid_ids = set(datamodel_ids)
    tokens = _tokenize(expr_text or "")
    if not tokens:
        raise AssignExprError("empty <assign expr=> body")

    pos = [0]

    def _peek() -> tuple[str, str] | None:
        if pos[0] < len(tokens):
            return tokens[pos[0]]
        return None

    def _eat(kind: str) -> tuple[str, str]:
        tok = _peek()
        if tok is None or tok[0] != kind:
            got = tok[1] if tok else "<end>"
            raise AssignExprError(
                f"expected {kind} but got '{got}' at token index {pos[0]}"
            )
        pos[0] += 1
        return tok

    def _parse_atom() -> AssignExpr:
        tok = _peek()
        if tok is None:
            raise AssignExprError("unexpected end of expression")
        kind, lex = tok
        if kind == "INT":
            pos[0] += 1
            try:
                v = int(lex, 0)
            except ValueError:
                raise AssignExprError(
                    f"malformed integer literal '{lex}'"
                ) from None
            return AssignExpr(kind="literal", value=v)
        if kind == "IDENT":
            pos[0] += 1
            # Boolean literals lower to integer constants per the
            # §15 wave-3-f-future-assign normative subset — `true` →
            # 1, `false` → 0.  Accepting them keeps wave-1/wave-2
            # boolean-flag charts (`<assign location="flag"
            # expr="true"/>`) lowering cleanly under the new walker
            # rather than rejecting them as unknown identifiers.
            if lex == "true":
                return AssignExpr(kind="literal", value=1)
            if lex == "false":
                return AssignExpr(kind="literal", value=0)
            if lex not in valid_ids:
                raise AssignExprError(
                    f"references unknown datamodel identifier '{lex}'"
                )
            return AssignExpr(kind="ident", ident=lex)
        if kind == "LPAREN":
            pos[0] += 1
            inner = _parse_expr()
            _eat("RPAREN")
            return inner
        if kind == "OTHER":
            # Specific message families for common rejected forms.
            if lex in ("*", "/", "%"):
                raise AssignExprError(
                    f"uses unsupported operator '{lex}'"
                )
            if lex.startswith('"') or lex.startswith("'"):
                raise AssignExprError(
                    f"contains a string literal {lex!r}"
                )
            if lex in ("==", "!=", "<", ">", "<=", ">="):
                raise AssignExprError(
                    f"uses unsupported comparison operator '{lex}'"
                )
            if lex in ("&&", "||", "!", "&", "|", "^", "~"):
                raise AssignExprError(
                    f"uses unsupported logical/bitwise operator '{lex}'"
                )
            if lex == "?":
                raise AssignExprError(
                    "uses a conditional/ternary expression"
                )
            raise AssignExprError(
                f"uses unsupported token '{lex}'"
            )
        raise AssignExprError(
            f"unexpected token '{lex}' (kind {kind})"
        )

    def _parse_unary() -> AssignExpr:
        tok = _peek()
        if tok is not None and tok[0] == "MINUS":
            pos[0] += 1
            # At v1 only unary minus on a literal (or parenthesised
            # literal) is permitted.  Function-call detection: if
            # an IDENT is followed by LPAREN treat as a call.
            inner = _parse_atom()
            if inner.kind != "literal":
                raise AssignExprError(
                    "uses unary minus on a non-literal operand; "
                    "supported: unary minus on integer literals only "
                    "(use binary minus '0 - x' for negated identifiers)"
                )
            return AssignExpr(kind="neg_literal", value=-inner.value)
        return _parse_atom()

    def _parse_expr() -> AssignExpr:
        # Detect function-call form (IDENT immediately followed by
        # LPAREN) before _parse_atom consumes the IDENT.
        tok = _peek()
        if (
            tok is not None
            and tok[0] == "IDENT"
            and pos[0] + 1 < len(tokens)
            and tokens[pos[0] + 1][0] == "LPAREN"
        ):
            name = tok[1]
            raise AssignExprError(
                f"contains a function call '{name}(...)'"
            )
        left = _parse_unary()
        while True:
            tok = _peek()
            if tok is None:
                break
            if tok[0] in ("PLUS", "MINUS"):
                op = "+" if tok[0] == "PLUS" else "-"
                pos[0] += 1
                right = _parse_unary()
                left = AssignExpr(
                    kind="binop", op=op, left=left, right=right
                )
                continue
            break
        return left

    tree = _parse_expr()
    if pos[0] != len(tokens):
        leftover_kind, leftover = tokens[pos[0]]
        # Translate trailing OTHER tokens into the same actionable
        # error messages the atom-position rejection emits, so a
        # rejected ECMA construct surfaces consistently regardless of
        # whether it appeared at the start of an expression or after
        # a valid prefix.
        if leftover_kind == "OTHER":
            if leftover in ("*", "/", "%"):
                raise AssignExprError(
                    f"uses unsupported operator '{leftover}'"
                )
            if leftover.startswith('"') or leftover.startswith("'"):
                raise AssignExprError(
                    f"contains a string literal {leftover!r}"
                )
            if leftover in ("==", "!=", "<", ">", "<=", ">="):
                raise AssignExprError(
                    f"uses unsupported comparison operator '{leftover}'"
                )
            if leftover in ("&&", "||", "!", "&", "|", "^", "~"):
                raise AssignExprError(
                    f"uses unsupported logical/bitwise operator '{leftover}'"
                )
            if leftover == "?":
                raise AssignExprError(
                    "uses a conditional/ternary expression"
                )
            raise AssignExprError(
                f"uses unsupported token '{leftover}'"
            )
        raise AssignExprError(
            f"trailing/unexpected token '{leftover}' after expression"
        )
    return tree


def _render_sv(node: AssignExpr, ident_signal_map: dict[str, str]) -> str:
    """Lower a parsed `AssignExpr` to SV right-hand-side text.

    `ident_signal_map` maps chart-side datamodel id → SV register name
    (e.g. ``"counter" -> "data_counter"``); the emitter appends ``_q``
    to read from the registered value.
    """
    if node.kind == "literal":
        return str(node.value)
    if node.kind == "neg_literal":
        return str(node.value)
    if node.kind == "ident":
        return f"{ident_signal_map[node.ident]}_q"
    if node.kind == "binop":
        left = _render_sv(node.left, ident_signal_map)
        right = _render_sv(node.right, ident_signal_map)
        return f"{left} {node.op} {right}"
    raise AssignExprError(f"unrenderable AssignExpr kind '{node.kind}'")


def _render_vhdl(
    node: AssignExpr, ident_signal_map: dict[str, str], width: int = 32
) -> str:
    """Lower a parsed `AssignExpr` to VHDL right-hand-side text.

    Integer literals are wrapped in ``to_signed(N, <width>)`` so the
    assignment to a ``signed`` datamodel register is well-typed.
    Datamodel idents (which are already ``signed`` registers) are
    emitted bare.
    """
    if node.kind == "literal":
        return f"to_signed({node.value}, {width})"
    if node.kind == "neg_literal":
        return f"to_signed({node.value}, {width})"
    if node.kind == "ident":
        return f"{ident_signal_map[node.ident]}_q"
    if node.kind == "binop":
        left = _render_vhdl(node.left, ident_signal_map, width)
        right = _render_vhdl(node.right, ident_signal_map, width)
        return f"{left} {node.op} {right}"
    raise AssignExprError(f"unrenderable AssignExpr kind '{node.kind}'")
