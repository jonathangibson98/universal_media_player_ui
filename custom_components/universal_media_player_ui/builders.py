"""Turn simple UI choices into templates and actions.

Nothing in here imports Home Assistant, so it is easy to test on its own.
The config flow asks the user plain questions ("which entity?", "which
service?") and these helpers write the Jinja templates / action lists that the
media player entity understands. Users never have to see or type either.
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Template builders
# --------------------------------------------------------------------------


def jq(text: Any) -> str:
    """Quote text as a Jinja string literal."""
    return "'" + str(text).replace("\\", "\\\\").replace("'", "\\'") + "'"


def jlist(items: list[str]) -> str:
    """Quote a list of strings as a Jinja list literal."""
    return "[" + ", ".join(jq(i) for i in items) + "]"


def tpl_entity_state(entity: str, scale_100: bool = False) -> str:
    """The state of an entity."""
    if scale_100:
        return (
            "{% set v = states(" + jq(entity) + ") | float(none) %}"
            "{{ (v / 100) if v is not none else '' }}"
        )
    return "{{ states(" + jq(entity) + ") }}"


def tpl_entity_attr(entity: str, attribute: str, scale_100: bool = False) -> str:
    """One attribute of an entity."""
    if scale_100:
        return (
            "{% set v = state_attr(" + jq(entity) + ", " + jq(attribute) + ") | float(none) %}"
            "{{ (v / 100) if v is not none else '' }}"
        )
    return "{{ state_attr(" + jq(entity) + ", " + jq(attribute) + ") }}"


def tpl_fixed(text: str) -> str:
    """A fixed piece of text (braces are escaped so it is never treated as a template)."""
    if any(mark in text for mark in ("{{", "{%", "{#")):
        return "{% raw %}" + text + "{% endraw %}"
    return text


def tpl_state_is(entity: str, values: list[str]) -> str:
    """True when the entity's state is one of the given values."""
    wanted = [v.lower() for v in values]
    return "{{ (states(" + jq(entity) + ") | lower) in " + jlist(wanted) + " }}"


PLAYER_STATES = ["playing", "paused", "idle", "on", "off", "standby", "buffering"]


def tpl_state_map(entity: str, mapping: dict[str, list[str]], fallback: str) -> str:
    """Translate an entity's states into media player states.

    `mapping` is {"playing": ["on", "streaming"], "off": ["off"], ...}.
    `fallback` is the media player state to use when nothing matches.
    """
    parts = ["{% set s = (states(" + jq(entity) + ") | lower) %}"]
    first = True
    for player_state in PLAYER_STATES:
        values = [v.lower() for v in mapping.get(player_state) or []]
        if not values:
            continue
        keyword = "if" if first else "elif"
        parts.append("{% " + keyword + " s in " + jlist(values) + " %}" + player_state)
        first = False
    if first:  # nothing mapped at all
        return fallback
    parts.append("{% else %}" + fallback + "{% endif %}")
    return "".join(parts)


def tpl_active_child(
    entity: str, states: list[str], child_yes: str, child_no: str | None = None
) -> str:
    """Pick the active child from the state of another entity."""
    wanted = [v.lower() for v in states]
    return (
        "{% if (states(" + jq(entity) + ") | lower) in " + jlist(wanted) + " %}"
        + child_yes
        + "{% else %}"
        + (child_no or "None")
        + "{% endif %}"
    )


# --------------------------------------------------------------------------
# Pure logic: which child is active, and what state the player shows
# --------------------------------------------------------------------------
# A child in one of these states is not "active" (same as the built-in universal player).
OFF_STATES = ("off", "idle", "unavailable", "unknown")
VALID_STATES = ("on", "off", "idle", "playing", "paused", "standby", "buffering")


def pick_active_child(children: list[str], get_state: Any) -> Any:
    """First child that is not off/idle/unavailable. `get_state(entity_id)` returns a state or None."""
    for entity_id in children:
        state = get_state(entity_id)
        if state is not None and state.state not in OFF_STATES:
            return state
    return None


def resolve_state(configured: bool, master: str | None, child_state: str | None) -> str:
    """Work out the state the universal player shows.

    configured   - a State setting exists (the "master" state)
    master       - what that setting currently says (None if it gave nothing usable)
    child_state  - state of the active child, or None when there is none

    Rules (same as the built-in universal player):
    * a master state of "off" always wins
    * otherwise the active child's state is used
    * with no active child, the master state is used (on, for example)
    * with no master state at all, no active child means off
    """
    if configured:
        value = (master or "off").strip().lower()
        if value not in VALID_STATES:
            value = "off"
        if value == "off":
            return "off"
        return child_state if child_state is not None else value
    return child_state if child_state is not None else "off"


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


def action_call(
    service: str, entity: str | None = None, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A 'call a service' action."""
    out: dict[str, Any] = {"action": service}
    if entity:
        out["target"] = {"entity_id": entity}
    if data:
        out["data"] = data
    return out


def action_delay(seconds: float) -> dict[str, Any]:
    """A 'wait' action."""
    value: float | int = int(seconds) if float(seconds).is_integer() else seconds
    return {"delay": {"seconds": value}}


def var(name: str) -> str:
    """Template that inserts a variable handed over by the media player."""
    return "{{ " + name + " }}"


# Variables the media player hands to the actions of each service.
SERVICE_VARS: dict[str, list[str]] = {
    "media_seek": ["position"],
    "volume_set": ["volume"],
    "volume_mute": ["mute"],
    "repeat_set": ["repeat"],
    "shuffle_set": ["shuffle"],
    "play_media": ["media_id", "media_type"],
    "join": ["group_members"],
    "select_source": ["source"],
    "select_sound_mode": ["sound_mode"],
}
SOURCE_VARS = ["source"]
SOUND_MODE_VARS = ["sound_mode"]

# What each variable means, shown to the user.
VAR_HELP: dict[str, str] = {
    "position": "the position to jump to, in seconds",
    "volume": "the new volume, from 0 to 1",
    "mute": "true or false",
    "repeat": "off, all or one",
    "shuffle": "true or false",
    "media_id": "what to play",
    "media_type": "the kind of media",
    "group_members": "the players to group with",
    "source": "the source that was picked",
    "active_child": "the media player that is currently active (may be empty)",
    "sound_mode": "the sound mode that was picked",
}

# --------------------------------------------------------------------------
# Presets: what you can do to each kind of entity
# --------------------------------------------------------------------------
# A field is something extra the service needs.
#   var="volume"  -> filled in automatically from the player's variable if it exists
#   var="*"       -> filled in with whatever the main variable is, if there is one
#   kind          -> text | number | bool | select | text_list
_F = dict

_NO_FIELDS: list[dict[str, Any]] = []

MEDIA_PLAYER_PRESETS: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("turn_on", "Turn on", _NO_FIELDS),
    ("turn_off", "Turn off", _NO_FIELDS),
    ("toggle", "Toggle on/off", _NO_FIELDS),
    ("media_play", "Play", _NO_FIELDS),
    ("media_pause", "Pause", _NO_FIELDS),
    ("media_stop", "Stop", _NO_FIELDS),
    ("media_play_pause", "Play / pause", _NO_FIELDS),
    ("media_next_track", "Next track", _NO_FIELDS),
    ("media_previous_track", "Previous track", _NO_FIELDS),
    (
        "media_seek",
        "Seek to a position",
        [_F(key="seek_position", label="Position (seconds)", kind="number", var="position", min=0, max=86400, step=1)],
    ),
    ("volume_up", "Volume up", _NO_FIELDS),
    ("volume_down", "Volume down", _NO_FIELDS),
    (
        "volume_set",
        "Set volume",
        [_F(key="volume_level", label="Volume (0 to 1)", kind="number", var="volume", min=0, max=1, step=0.01)],
    ),
    (
        "volume_mute",
        "Mute / unmute",
        [_F(key="is_volume_muted", label="Mute", kind="bool", var="mute", default=True)],
    ),
    (
        "select_source",
        "Select a source",
        [_F(key="source", label="Source name", kind="text", var="source")],
    ),
    (
        "select_sound_mode",
        "Select a sound mode",
        [_F(key="sound_mode", label="Sound mode name", kind="text", var="sound_mode")],
    ),
    (
        "repeat_set",
        "Set repeat",
        [_F(key="repeat", label="Repeat", kind="select", var="repeat", options=["off", "all", "one"])],
    ),
    (
        "shuffle_set",
        "Set shuffle",
        [_F(key="shuffle", label="Shuffle", kind="bool", var="shuffle", default=True)],
    ),
    (
        "play_media",
        "Play media",
        [
            _F(key="media_content_id", label="Media to play", kind="text", var="media_id"),
            _F(key="media_content_type", label="Media type", kind="text", var="media_type"),
        ],
    ),
    ("clear_playlist", "Clear playlist", _NO_FIELDS),
    (
        "join",
        "Group with other players",
        [_F(key="group_members", label="Players to group with", kind="text_list", var="group_members")],
    ),
    ("unjoin", "Leave group", _NO_FIELDS),
]

_ON_OFF_TOGGLE = [
    ("turn_on", "Turn on", _NO_FIELDS),
    ("turn_off", "Turn off", _NO_FIELDS),
    ("toggle", "Toggle", _NO_FIELDS),
]

# domain -> [(service, label, fields)]
PRESETS: dict[str, list[tuple[str, str, list[dict[str, Any]]]]] = {
    "media_player": MEDIA_PLAYER_PRESETS,
    "button": [("press", "Press the button", _NO_FIELDS)],
    "input_button": [("press", "Press the button", _NO_FIELDS)],
    "switch": _ON_OFF_TOGGLE,
    "input_boolean": _ON_OFF_TOGGLE,
    "light": _ON_OFF_TOGGLE,
    "fan": _ON_OFF_TOGGLE,
    "script": [("turn_on", "Run the script", _NO_FIELDS)],
    "scene": [("turn_on", "Activate the scene", _NO_FIELDS)],
    "automation": [
        ("trigger", "Trigger the automation", _NO_FIELDS),
        ("turn_on", "Enable the automation", _NO_FIELDS),
        ("turn_off", "Disable the automation", _NO_FIELDS),
    ],
    "remote": _ON_OFF_TOGGLE
    + [
        (
            "send_command",
            "Send a remote command",
            [
                _F(key="command", label="Command (separate several with commas)", kind="text_list"),
                _F(key="device", label="Device (optional)", kind="text", optional=True),
            ],
        )
    ],
    "cover": [
        ("open_cover", "Open", _NO_FIELDS),
        ("close_cover", "Close", _NO_FIELDS),
        ("stop_cover", "Stop", _NO_FIELDS),
        ("toggle", "Toggle", _NO_FIELDS),
    ],
    "lock": [("lock", "Lock", _NO_FIELDS), ("unlock", "Unlock", _NO_FIELDS)],
    "input_select": [
        ("select_option", "Choose an option", [_F(key="option", label="Option", kind="text", var="*")])
    ],
    "select": [
        ("select_option", "Choose an option", [_F(key="option", label="Option", kind="text", var="*")])
    ],
    "input_number": [
        ("set_value", "Set the number", [_F(key="value", label="Value", kind="number", var="*", min=-100000, max=100000, step=0.01)])
    ],
    "number": [
        ("set_value", "Set the number", [_F(key="value", label="Value", kind="number", var="*", min=-100000, max=100000, step=0.01)])
    ],
    "input_text": [
        ("set_value", "Set the text", [_F(key="value", label="Text", kind="text", var="*")])
    ],
}

# Used when the picked entity's domain has no presets.
GENERIC_PRESETS = [
    ("homeassistant.turn_on", "Turn on", _NO_FIELDS),
    ("homeassistant.turn_off", "Turn off", _NO_FIELDS),
    ("homeassistant.toggle", "Toggle", _NO_FIELDS),
]


def presets_for(domain: str) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """Presets for a domain, as (full service name, label, fields)."""
    if domain in PRESETS:
        return [(f"{domain}.{svc}", label, fields) for svc, label, fields in PRESETS[domain]]
    return list(GENERIC_PRESETS)


def find_preset(full_service: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Look up (label, fields) for 'domain.service'."""
    domain = full_service.split(".", 1)[0]
    for svc, label, fields in presets_for(domain):
        if svc == full_service:
            return label, fields
    return None


def _resolve_var(field: dict[str, Any], available: list[str]) -> str | None:
    """Which variable (if any) fills this field automatically."""
    wanted = field.get("var")
    if not wanted:
        return None
    if wanted == "*":
        return available[0] if available else None
    return wanted if wanted in available else None


def fields_to_ask(fields: list[dict[str, Any]], available: list[str]) -> list[dict[str, Any]]:
    """The fields the user has to fill in (the rest are filled in automatically)."""
    return [f for f in fields if _resolve_var(f, available) is None]


def wants_scale_option(fields: list[dict[str, Any]], available: list[str]) -> bool:
    """True when a 0-1 volume is passed to a field that probably wants 0-100."""
    return (
        bool(available)
        and available[0] == "volume"
        and any(f.get("var") == "*" and _resolve_var(f, available) for f in fields)
    )


def build_data(
    fields: list[dict[str, Any]],
    available: list[str],
    answers: dict[str, Any],
    scale_100: bool = False,
) -> dict[str, Any]:
    """Make the `data:` block for a service call."""
    data: dict[str, Any] = {}
    for field in fields:
        key = field["key"]
        name = _resolve_var(field, available)
        if name is not None:
            if name == "volume" and field.get("var") == "*" and scale_100:
                data[key] = "{{ (volume * 100) | round(0) }}"
            else:
                data[key] = var(name)
            continue
        value = answers.get(key)
        if value in (None, ""):
            continue
        if field["kind"] == "text_list":
            items = [p.strip() for p in str(value).split(",") if p.strip()]
            value = items if len(items) > 1 else (items[0] if items else None)
            if value is None:
                continue
        elif field["kind"] == "number" and float(value).is_integer():
            value = int(value)
        data[key] = value
    return data


def build_forward(
    service: str,
    entity: str,
    available: list[str],
    override_name: str | None = None,
) -> dict[str, Any]:
    """Pass a call straight through to another media player."""
    found = find_preset(f"media_player.{service}")
    fields = found[1] if found else []
    data = build_data(fields, available, {})
    # sources / sound modes can be called something different on the other device
    if override_name:
        for field in fields:
            if field.get("var") in ("source", "sound_mode"):
                data[field["key"]] = tpl_fixed(override_name)
    return action_call(f"media_player.{service}", entity, data)


def build_forward_active(service: str, available: list[str]) -> dict[str, Any]:
    """Pass a call on to whichever child is active right now (does nothing if none is)."""
    call = build_forward(service, "{{ active_child }}", available)
    return {
        "if": [{"condition": "template", "value_template": "{{ active_child is not none }}"}],
        "then": [call],
    }
