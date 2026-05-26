"""Read-only SOS-11 chart query helpers over raw scjson dictionaries."""

from __future__ import annotations

from typing import Any, Iterable


ChartDict = dict[str, Any]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _iter_child_nodes(node: ChartDict) -> Iterable[tuple[str, ChartDict]]:
    for kind in ("state", "parallel"):
        for child in _as_list(node.get(kind)):
            if isinstance(child, dict):
                yield kind, child


def _iter_states(raw: ChartDict) -> Iterable[tuple[str, ChartDict]]:
    for kind, child in _iter_child_nodes(raw):
        yield kind, child
        yield from _iter_states(child)


def _normalise_target(target: Any) -> list[str]:
    return [str(item) for item in _as_list(target) if item is not None]


def _event_names(event: Any) -> list[str]:
    if event is None:
        return []
    if isinstance(event, list):
        return [str(item) for item in event if item is not None]
    return [part for part in str(event).split() if part]


def _state_initial(st: ChartDict) -> list[str]:
    if "initial_attribute" in st:
        return [str(item) for item in _as_list(st.get("initial_attribute"))]
    if "initial" in st:
        return [str(item) for item in _as_list(st.get("initial"))]
    return []


def _transition_summary(source: str, tr: ChartDict) -> dict[str, Any]:
    return {
        "source": source,
        "target": _normalise_target(tr.get("target")),
        "event": tr.get("event"),
        "cond": tr.get("cond"),
    }


def _state_summary(kind: str, st: ChartDict) -> dict[str, Any]:
    state_id = st.get("id")
    children = [
        {"id": child.get("id"), "kind": child_kind}
        for child_kind, child in _iter_child_nodes(st)
        if child.get("id") is not None
    ]
    transitions = [
        _transition_summary(str(state_id), tr)
        for tr in _as_list(st.get("transition"))
        if isinstance(tr, dict)
    ]
    return {
        "id": state_id,
        "kind": kind,
        "initial": _state_initial(st),
        "children": children,
        "transitions": transitions,
    }


def query_state(raw: ChartDict, id: str) -> dict[str, Any]:
    """Return the state or parallel structure for a chart state id."""
    for kind, st in _iter_states(raw):
        if st.get("id") == id:
            return _state_summary(kind, st)
    raise KeyError(f"state id not found: {id}")


def query_transitions(
    raw: ChartDict,
    source: str | None = None,
    target: str | None = None,
    event: str | None = None,
) -> list[dict[str, Any]]:
    """Return transitions matching optional source, target, and event filters."""
    out: list[dict[str, Any]] = []
    for _kind, st in _iter_states(raw):
        state_id = st.get("id")
        if state_id is None:
            continue
        state_id = str(state_id)
        if source is not None and state_id != source:
            continue
        for tr in _as_list(st.get("transition")):
            if not isinstance(tr, dict):
                continue
            targets = _normalise_target(tr.get("target"))
            event_names = _event_names(tr.get("event"))
            if target is not None and target not in targets:
                continue
            if event is not None and event not in event_names:
                continue
            out.append(_transition_summary(state_id, tr))
    return out


def query_event_vocabulary(raw: ChartDict) -> list[str]:
    """Derive the sorted v1 event vocabulary from transition event names."""
    events: set[str] = set()
    for tr in query_transitions(raw):
        events.update(_event_names(tr.get("event")))
    return sorted(events)


def _iter_datamodel_entries(node: ChartDict) -> Iterable[dict[str, Any]]:
    for dm in _as_list(node.get("datamodel")):
        if not isinstance(dm, dict):
            continue
        for data in _as_list(dm.get("data")):
            if isinstance(data, dict):
                yield data
    for _kind, child in _iter_child_nodes(node):
        yield from _iter_datamodel_entries(child)


def query_datamodel_entries(raw: ChartDict) -> list[dict[str, Any]]:
    """Return chart datamodel entries in document order."""
    entries: list[dict[str, Any]] = []
    for data in _iter_datamodel_entries(raw):
        entry = {
            "id": data.get("id", ""),
            "expr": data.get("expr", ""),
        }
        if "type" in data:
            entry["type"] = data.get("type")
        entries.append(entry)
    return entries


def query_invariants(raw: ChartDict, state: str | None = None) -> list[dict[str, Any]]:
    """Return per-chart invariants when a future chart grammar defines them."""
    # SOS-11 intentionally leaves the per-chart invariant grammar to callers.
    # Until charts carry explicit invariant metadata, the read-only query has
    # no chart-owned invariant records to expose.
    _ = raw
    _ = state
    return []
