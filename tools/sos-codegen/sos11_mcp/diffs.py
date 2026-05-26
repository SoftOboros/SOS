"""SOS-11 structured SCXML diff helpers over raw scjson dictionaries."""

from __future__ import annotations

import difflib
import json
from typing import Any, Iterable, Mapping

from sos11_mcp.contracts import ScxmlDiff


ChartDict = dict[str, Any]
JsonObject = dict[str, Any]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _json_stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_stable(item) for item in value]
    if isinstance(value, tuple):
        return [_json_stable(item) for item in value]
    return value


def _sort_key(value: Any) -> str:
    return json.dumps(_json_stable(value), sort_keys=True, separators=(",", ":"))


def _iter_child_nodes(node: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for kind in ("state", "parallel"):
        for child in _as_list(node.get(kind)):
            if isinstance(child, Mapping):
                yield kind, child


def _iter_states(
    raw: Mapping[str, Any],
    parent_id: str | None = None,
) -> Iterable[tuple[str, Mapping[str, Any], str | None]]:
    for kind, child in _iter_child_nodes(raw):
        yield kind, child, parent_id
        child_id = child.get("id")
        yield from _iter_states(child, str(child_id) if child_id is not None else None)


def _normalise_target(target: Any) -> list[str]:
    return [str(item) for item in _as_list(target) if item is not None]


def _event_names(event: Any) -> list[str]:
    if event is None:
        return []
    if isinstance(event, list):
        return [str(item) for item in event if item is not None]
    return [part for part in str(event).split() if part]


def _state_initial(st: Mapping[str, Any]) -> list[str]:
    if "initial_attribute" in st:
        return [str(item) for item in _as_list(st.get("initial_attribute"))]
    if "initial" in st:
        return [str(item) for item in _as_list(st.get("initial"))]
    return []


def _state_summary(
    kind: str,
    st: Mapping[str, Any],
    parent_id: str | None,
) -> JsonObject:
    return {
        "id": str(st.get("id", "")),
        "kind": kind,
        "parent": parent_id,
        "initial": _state_initial(st),
    }


def _state_map(raw: Mapping[str, Any]) -> dict[str, JsonObject]:
    states: dict[str, JsonObject] = {}
    for kind, st, parent_id in _iter_states(raw):
        state_id = st.get("id")
        if state_id is not None:
            states[str(state_id)] = _state_summary(kind, st, parent_id)
    return states


def _transition_identity(
    source: str,
    event: list[str],
    target: list[str],
    cond: Any,
    occurrence: int,
) -> str:
    payload = {
        "source": source,
        "event": event,
        "target": target,
        "cond": cond,
        "occurrence": occurrence,
    }
    return _sort_key(payload)


def _transition_map(raw: Mapping[str, Any]) -> dict[str, JsonObject]:
    transitions: dict[str, JsonObject] = {}
    occurrences: dict[tuple[str, tuple[str, ...], tuple[str, ...], str], int] = {}
    order = 0
    for _kind, st, _parent_id in _iter_states(raw):
        source = st.get("id")
        if source is None:
            continue
        source_id = str(source)
        for tr in _as_list(st.get("transition")):
            if not isinstance(tr, Mapping):
                continue
            event = _event_names(tr.get("event"))
            target = _normalise_target(tr.get("target"))
            cond = tr.get("cond")
            occurrence_key = (source_id, tuple(event), tuple(target), _sort_key(cond))
            occurrence = occurrences.get(occurrence_key, 0) + 1
            occurrences[occurrence_key] = occurrence
            transition_id = _transition_identity(
                source=source_id,
                event=event,
                target=target,
                cond=cond,
                occurrence=occurrence,
            )
            transitions[transition_id] = {
                "id": transition_id,
                "source": source_id,
                "event": event,
                "target": target,
                "cond": cond,
                "occurrence": occurrence,
                "order": order,
            }
            order += 1
    return transitions


def _iter_datamodel_entries(raw: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for dm in _as_list(raw.get("datamodel")):
        if not isinstance(dm, Mapping):
            continue
        for data in _as_list(dm.get("data")):
            if isinstance(data, Mapping):
                yield data
    for _kind, child in _iter_child_nodes(raw):
        yield from _iter_datamodel_entries(child)


def _datamodel_map(raw: Mapping[str, Any]) -> dict[str, JsonObject]:
    entries: dict[str, JsonObject] = {}
    anonymous_index = 0
    for data in _iter_datamodel_entries(raw):
        entry = _json_stable(dict(data))
        data_id = entry.get("id")
        if data_id is None:
            data_id = f"@anonymous:{anonymous_index}"
            anonymous_index += 1
            entry = {"id": data_id, **entry}
        entries[str(data_id)] = entry
    return entries


def _event_vocabulary(raw: Mapping[str, Any]) -> set[str]:
    events: set[str] = set()
    for transition in _transition_map(raw).values():
        events.update(str(event) for event in transition["event"])
    return events


def _added_removed(
    before: Mapping[str, JsonObject],
    after: Mapping[str, JsonObject],
) -> tuple[list[JsonObject], list[JsonObject]]:
    added = [after[key] for key in sorted(set(after) - set(before))]
    removed = [before[key] for key in sorted(set(before) - set(after))]
    return added, removed


def structured_scxml_diff(before: ChartDict, after: ChartDict) -> JsonObject:
    """Return the canonical SOS-11 semantic diff for two raw scjson charts."""
    before_states = _state_map(before)
    after_states = _state_map(after)
    before_transitions = _transition_map(before)
    after_transitions = _transition_map(after)
    before_datamodel = _datamodel_map(before)
    after_datamodel = _datamodel_map(after)

    states_added, states_removed = _added_removed(before_states, after_states)
    transitions_added, transitions_removed = _added_removed(
        before_transitions,
        after_transitions,
    )
    datamodel_added, datamodel_removed = _added_removed(
        before_datamodel,
        after_datamodel,
    )

    changed_datamodel = [
        {
            "id": key,
            "before": before_datamodel[key],
            "after": after_datamodel[key],
        }
        for key in sorted(set(before_datamodel) & set(after_datamodel))
        if before_datamodel[key] != after_datamodel[key]
    ]

    before_events = _event_vocabulary(before)
    after_events = _event_vocabulary(after)

    return {
        "version": 1,
        "states": {
            "added": sorted(states_added, key=_sort_key),
            "removed": sorted(states_removed, key=_sort_key),
        },
        "transitions": {
            "added": sorted(transitions_added, key=_sort_key),
            "removed": sorted(transitions_removed, key=_sort_key),
        },
        "datamodel": {
            "added": sorted(datamodel_added, key=_sort_key),
            "removed": sorted(datamodel_removed, key=_sort_key),
            "changed": sorted(changed_datamodel, key=_sort_key),
        },
        "events": {
            "added": sorted(after_events - before_events),
            "removed": sorted(before_events - after_events),
        },
    }


def render_unified_diff(
    before_xml: str,
    after_xml: str,
    *,
    fromfile: str = "before.scxml",
    tofile: str = "after.scxml",
) -> str:
    """Render a unified diff for two SCXML/XML strings."""
    return "".join(
        difflib.unified_diff(
            before_xml.splitlines(keepends=True),
            after_xml.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


def build_scxml_diff(
    before: ChartDict,
    after: ChartDict,
    *,
    before_xml: str | None = None,
    after_xml: str | None = None,
    fromfile: str = "before.scxml",
    tofile: str = "after.scxml",
) -> ScxmlDiff:
    """Build the contracts.ScxmlDiff payload for a SOS-11 tool-call result."""
    rendered = None
    if before_xml is not None and after_xml is not None:
        rendered = render_unified_diff(
            before_xml,
            after_xml,
            fromfile=fromfile,
            tofile=tofile,
        )
    return ScxmlDiff(
        ast_diff=structured_scxml_diff(before, after),
        rendered_unified_diff=rendered,
    )
