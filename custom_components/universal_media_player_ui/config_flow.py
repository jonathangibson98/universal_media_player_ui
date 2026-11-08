"""Config flow + options flow: create and edit the media player from the UI.

Everything here is point-and-click. You pick from lists ("which entity?",
"which service?", "which states mean playing?") and the integration writes
the templates and actions for you. The old free-form template / YAML pages
are still there, tucked away under "Advanced", for anyone who wants them.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.template import Template

from . import builders as b
from .const import (
    ATTRIBUTE_INFO,
    ATTRIBUTES_MEDIA,
    ATTRIBUTES_PLAYER,
    BACK,
    BOOL_ATTRIBUTES,
    CONF_ACTIVE_CHILD,
    CONF_ATTRIBUTES,
    CONF_BROWSE,
    CONF_CHILDREN,
    CONF_CUSTOM_ATTRIBUTES,
    CONF_DEVICE_CLASS,
    CONF_ICON,
    CONF_SEARCH,
    CONF_SERVICE_SCRIPTS,
    CONF_SOUND_MODE_SCRIPTS,
    CONF_SOURCE_SCRIPTS,
    CONF_STATE,
    DOMAIN,
    SERVICE_INFO,
    SERVICES_OTHER,
    SERVICES_PLAYBACK,
    SERVICES_POWER,
)

# ---------------------------------------------------------------- selectors
TEMPLATE = selector.TemplateSelector()
ACTIONS = selector.ActionSelector()
OBJECT = selector.ObjectSelector()
ICON = selector.IconSelector()
TEXT = selector.TextSelector()
BOOLEAN = selector.BooleanSelector()
ANY_ENTITY = selector.EntitySelector()
MEDIA_PLAYER = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player")
)
MEDIA_PLAYERS = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", multiple=True)
)


def _opt(value: str, label: str) -> selector.SelectOptionDict:
    return selector.SelectOptionDict(value=value, label=label)


def _select(
    options: list[Any],
    *,
    multiple: bool = False,
    custom: bool = False,
    mode: selector.SelectSelectorMode = selector.SelectSelectorMode.DROPDOWN,
) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, multiple=multiple, custom_value=custom, mode=mode
        )
    )


DEVICE_CLASS = _select(["tv", "speaker", "receiver"])
LIST = selector.SelectSelectorMode.LIST

EMPTY = (None, "", [], {})

# What the user can pick for each kind of value
MODE_LABELS = {
    "inherit": "Use the active child's value (or leave empty)",
    "entity_state": "Use the state of an entity",
    "entity_attr": "Use one attribute of an entity",
    "fixed": "Type a fixed value",
    "state_is": "Yes / no: yes while an entity is in certain states",
    "state_map": "Follow another entity (you choose which of its states mean on, off, playing...)",
    "active_when": "Switch child depending on another entity's state",
    "custom": "Advanced: write a template myself",
}

# States people commonly want to pick, by entity type
COMMON_STATES: dict[str, list[str]] = {
    "media_player": ["playing", "paused", "idle", "on", "off", "standby", "buffering"],
    "cover": ["open", "closed", "opening", "closing"],
    "lock": ["locked", "unlocked"],
    "person": ["home", "not_home"],
    "device_tracker": ["home", "not_home"],
    "vacuum": ["cleaning", "docked", "idle", "paused", "returning"],
    "climate": ["off", "heat", "cool", "auto", "heat_cool", "dry", "fan_only"],
    "binary_sensor": ["on", "off"],
}
DEFAULT_STATES = ["on", "off"]
EXTRA_STATES = ["unavailable", "unknown"]

PLAYER_STATE_LABELS = {
    "playing": "playing",
    "paused": "paused",
    "idle": "idle",
    "on": "on",
    "off": "off",
    "standby": "standby",
    "buffering": "buffering",
}


class UniversalMediaPlayerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a new universal media player."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UniversalMediaPlayerOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = dict(user_input)
            name = data.pop(CONF_NAME)
            options = {k: v for k, v in data.items() if v not in EMPTY}
            return self.async_create_entry(title=name, data={}, options=options)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TEXT,
                vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASS,
                vol.Optional(CONF_CHILDREN): MEDIA_PLAYERS,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
        )


class UniversalMediaPlayerOptionsFlow(OptionsFlow):
    """Edit everything about the player. Each completed choice saves right away."""

    def __init__(self) -> None:
        self._options: dict[str, Any] | None = None
        self._ctx: dict[str, Any] = {}

    # ================================================================ helpers
    def _current(self) -> dict[str, Any]:
        if self._options is None:
            self._options = deepcopy(dict(self.config_entry.options))
        return self._options

    def _save(self) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=deepcopy(self._current())
        )

    async def _goto(self, step: str) -> ConfigFlowResult:
        return await getattr(self, f"async_step_{step}")()

    def _ph(self, **extra: Any) -> dict[str, str]:
        """Description placeholders. Every key is always present."""
        base = {
            "name": "",
            "label": "",
            "current": "",
            "entity": "",
            "count": "",
            "summary": "",
            "help": "",
            "vars": "",
            "example": "",
        }
        base.update({k: str(v) for k, v in extra.items()})
        return base

    def _validate(self, user_input: dict[str, Any], kinds: dict[str, str]) -> dict[str, str]:
        errors: dict[str, str] = {}
        for key, kind in kinds.items():
            value = user_input.get(key)
            if value in EMPTY:
                continue
            if kind == "template":
                try:
                    Template(value, self.hass).ensure_valid()
                except TemplateError:
                    errors[key] = "invalid_template"
            elif kind == "actions":
                try:
                    cv.SCRIPT_SCHEMA(value)
                except vol.Invalid:
                    errors[key] = "invalid_actions"
            elif kind == "object":
                if not isinstance(value, dict):
                    errors[key] = "invalid_object"
            elif kind == "templates_dict":
                if not isinstance(value, dict):
                    errors[key] = "invalid_object"
                    continue
                for item in value.values():
                    try:
                        Template(str(item), self.hass).ensure_valid()
                    except TemplateError:
                        errors[key] = "invalid_template"
                        break
        return errors

    def _entity_attributes(self, entity_id: str) -> list[str]:
        state = self.hass.states.get(entity_id)
        return sorted(state.attributes) if state else []

    def _state_options(self, entity_id: str) -> list[str]:
        """Handy states to pick from for this entity."""
        domain = entity_id.split(".", 1)[0]
        out: list[str] = []
        state = self.hass.states.get(entity_id)
        if state is not None and state.state not in EXTRA_STATES:
            out.append(state.state)
        for item in COMMON_STATES.get(domain, DEFAULT_STATES) + EXTRA_STATES:
            if item not in out:
                out.append(item)
        return out

    # ---------------------------------------------------- generic form pages
    async def _group_step(
        self,
        step_id: str,
        fields: dict[str, Any],
        bucket: str | None,
        user_input: dict[str, Any] | None,
        kinds: dict[str, str] | None = None,
        back: str = "init",
    ) -> ConfigFlowResult:
        """One simple form page. `bucket` is a nested dict key in options (or None = top level)."""
        opts = self._current()
        current = opts.get(bucket, {}) if bucket else opts
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = self._validate(user_input, kinds or {})
            if not errors:
                new = dict(current)
                for key in fields:
                    value = user_input.get(key)
                    if value in EMPTY:
                        new.pop(key, None)
                    else:
                        new[key] = value
                if bucket:
                    if new:
                        opts[bucket] = new
                    else:
                        opts.pop(bucket, None)
                else:
                    opts.clear()
                    opts.update(new)
                self._save()
                return await self._goto(back)

        schema = vol.Schema({vol.Optional(k): sel for k, sel in fields.items()})
        suggested = (
            user_input
            if user_input is not None
            else {k: current[k] for k in fields if k in current}
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=self._ph(),
        )

    # ==================================================================== menu
    def _summary(self) -> str:
        opts = self._current()
        lines = []
        children = opts.get(CONF_CHILDREN) or []
        lines.append(f"Children: {', '.join(children)}" if children else "Children: none")
        lines.append(f"State: {'set' if opts.get(CONF_STATE) else 'follows the active child'}")
        lines.append(f"Active child: {'custom' if opts.get(CONF_ACTIVE_CHILD) else 'first one that is playing'}")
        lines.append(f"Attributes set: {len(opts.get(CONF_ATTRIBUTES) or {})}")
        lines.append(f"Actions set: {len(opts.get(CONF_SERVICE_SCRIPTS) or {})}")
        lines.append(f"Sources: {len(opts.get(CONF_SOURCE_SCRIPTS) or {})}")
        lines.append(f"Sound modes: {len(opts.get(CONF_SOUND_MODE_SCRIPTS) or {})}")
        return "  \n".join(lines)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "state",
                "active_child",
                "attributes_media",
                "attributes_player",
                "custom_attrs",
                "actions_playback",
                "actions_power",
                "actions_other",
                "sources",
                "sound_modes",
                "advanced",
                "finish",
            ],
            description_placeholders=self._ph(summary=self._summary()),
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=deepcopy(self._current()))

    # ================================================================ general
    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "general",
            {
                CONF_DEVICE_CLASS: DEVICE_CLASS,
                CONF_ICON: ICON,
                CONF_CHILDREN: MEDIA_PLAYERS,
                CONF_BROWSE: MEDIA_PLAYER,
                CONF_SEARCH: MEDIA_PLAYER,
            },
            None,
            user_input,
        )

    # =========================================================================
    # VALUE WIZARD: state, availability, attributes, custom attributes.
    # Ask "where does this come from?" then write the template for the user.
    # =========================================================================
    def _target_label(self) -> str:
        kind, name = self._ctx["kind"], self._ctx.get("name", "")
        if kind == "state":
            return "State"
        if kind == "active":
            return "Active child"
        if kind == "attr":
            return ATTRIBUTE_INFO[name][0]
        return name

    def _target_get(self) -> str | None:
        opts, kind, name = self._current(), self._ctx["kind"], self._ctx.get("name")
        if kind == "state":
            return opts.get(CONF_STATE)
        if kind == "active":
            return opts.get(CONF_ACTIVE_CHILD)
        key = CONF_ATTRIBUTES if kind == "attr" else CONF_CUSTOM_ATTRIBUTES
        value = (opts.get(key) or {}).get(name)
        return None if value is None else str(value)

    def _target_set(self, template: str | None) -> None:
        opts, kind, name = self._current(), self._ctx["kind"], self._ctx.get("name")
        if kind in ("state", "active"):
            key = CONF_STATE if kind == "state" else CONF_ACTIVE_CHILD
            if template:
                opts[key] = template
            else:
                opts.pop(key, None)
            return
        key = CONF_ATTRIBUTES if kind == "attr" else CONF_CUSTOM_ATTRIBUTES
        bucket = dict(opts.get(key) or {})
        if template:
            bucket[name] = template
        else:
            bucket.pop(name, None)
        if bucket:
            opts[key] = bucket
        else:
            opts.pop(key, None)

    async def _value_done(self, template: str | None) -> ConfigFlowResult:
        self._target_set(template)
        self._save()
        return await self._goto(self._ctx["back"])

    def _wants_scale(self, mode: str) -> bool:
        return (
            self._ctx["kind"] == "attr"
            and self._ctx.get("name") == "volume_level"
            and mode in ("entity_state", "entity_attr")
        )

    def _modes_for_target(self) -> list[str]:
        kind, name = self._ctx["kind"], self._ctx.get("name")
        if kind == "state":
            return ["inherit", "state_map", "entity_state", "entity_attr", "custom"]
        if kind == "active":
            return ["inherit", "active_when", "custom"]
        modes = ["inherit"] if kind == "attr" else []
        modes += ["entity_state", "entity_attr", "fixed"]
        if kind == "attr" and name in BOOL_ATTRIBUTES:
            modes.append("state_is")
        modes.append("custom")
        return modes

    # -- entry points from the menu ------------------------------------------
    async def async_step_state(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._ctx = {"kind": "state", "back": "init"}
        return await self.async_step_value_start()

    async def async_step_active_child(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._ctx = {"kind": "active", "back": "init"}
        return await self.async_step_value_start()

    async def _pick_attribute(
        self, step_id: str, names: list[str], user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        configured = self._current().get(CONF_ATTRIBUTES) or {}
        if user_input is not None:
            choice = user_input["choice"]
            if choice == BACK:
                return await self.async_step_init()
            self._ctx = {"kind": "attr", "name": choice, "back": step_id}
            return await self.async_step_value_start()
        options = []
        for name in names:
            label, hint = ATTRIBUTE_INFO[name]
            mark = "✓ " if name in configured else ""
            options.append(_opt(name, f"{mark}{label}" + (f" ({hint})" if hint else "")))
        options.append(_opt(BACK, "← Back to the main menu"))
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required("choice"): _select(options, mode=LIST)}),
            description_placeholders=self._ph(),
        )

    async def async_step_attributes_media(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._pick_attribute("attributes_media", ATTRIBUTES_MEDIA, user_input)

    async def async_step_attributes_player(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._pick_attribute("attributes_player", ATTRIBUTES_PLAYER, user_input)

    # -- step 1: where does the value come from? -----------------------------
    async def async_step_value_start(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            mode = user_input["mode"]
            self._ctx["mode"] = mode
            if mode == "inherit":
                return await self._value_done(None)
            if mode == "custom":
                return await self.async_step_value_custom()
            if mode == "fixed":
                return await self.async_step_value_fixed()
            if mode == "active_when":
                return await self.async_step_value_active_when()
            return await self.async_step_value_entity()

        options = [_opt(m, MODE_LABELS[m]) for m in self._modes_for_target()]
        current = self._target_get()
        help_text = ""
        if self._ctx["kind"] == "attr":
            help_text = ATTRIBUTE_INFO[self._ctx["name"]][1]
        elif self._ctx["kind"] == "state":
            help_text = (
                "Optional. Leave it as it is to copy the active child. Set it when something else "
                "decides whether the player is on or off (a switch, a remote...). "
                "An 'off' here always wins over the children."
            )
        elif self._ctx["kind"] == "active":
            help_text = (
                "By default the player follows the first child that is not off or idle. "
                "Change that here if you need to pick the child yourself."
            )
        return self.async_show_form(
            step_id="value_start",
            data_schema=vol.Schema({vol.Required("mode"): _select(options, mode=LIST)}),
            description_placeholders=self._ph(
                label=self._target_label(),
                help=help_text,
                current=f"`{current}`" if current else "not set",
            ),
        )

    # -- step 2: pick the entity ---------------------------------------------
    async def async_step_value_entity(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        mode = self._ctx["mode"]
        if user_input is not None:
            entity = user_input["entity"]
            self._ctx["entity"] = entity
            scale = bool(user_input.get("scale_100"))
            if mode == "entity_state":
                return await self._value_done(b.tpl_entity_state(entity, scale))
            if mode == "entity_attr":
                return await self.async_step_value_attribute()
            if mode == "state_map":
                return await self.async_step_value_state_map()
            return await self.async_step_value_states()  # state_is / state_in

        fields: dict[Any, Any] = {vol.Required("entity"): ANY_ENTITY}
        if self._wants_scale(mode) and mode == "entity_state":
            fields[vol.Optional("scale_100", default=False)] = BOOLEAN
        return self.async_show_form(
            step_id="value_entity",
            data_schema=vol.Schema(fields),
            description_placeholders=self._ph(label=self._target_label()),
        )

    async def async_step_value_attribute(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entity = self._ctx["entity"]
        if user_input is not None:
            attribute = str(user_input["attribute"]).strip()
            scale = bool(user_input.get("scale_100"))
            return await self._value_done(b.tpl_entity_attr(entity, attribute, scale))

        names = self._entity_attributes(entity)
        sel = _select(names, custom=True) if names else TEXT
        fields: dict[Any, Any] = {vol.Required("attribute"): sel}
        if self._wants_scale("entity_attr"):
            fields[vol.Optional("scale_100", default=False)] = BOOLEAN
        return self.async_show_form(
            step_id="value_attribute",
            data_schema=vol.Schema(fields),
            description_placeholders=self._ph(label=self._target_label(), entity=entity),
        )

    async def async_step_value_states(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entity = self._ctx["entity"]
        if user_input is not None:
            values = [str(v) for v in user_input["states"]]
            return await self._value_done(b.tpl_state_is(entity, values))
        return self.async_show_form(
            step_id="value_states",
            data_schema=vol.Schema(
                {
                    vol.Required("states"): _select(
                        self._state_options(entity), multiple=True, custom=True
                    )
                }
            ),
            description_placeholders=self._ph(label=self._target_label(), entity=entity),
        )

    async def async_step_value_state_map(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entity = self._ctx["entity"]
        if user_input is not None:
            mapping = {
                s: [str(v) for v in user_input.get(f"when_{s}") or []]
                for s in b.PLAYER_STATES
            }
            return await self._value_done(
                b.tpl_state_map(entity, mapping, user_input.get("fallback", "off"))
            )
        options = self._state_options(entity)
        fields: dict[Any, Any] = {
            vol.Optional(f"when_{s}"): _select(options, multiple=True, custom=True)
            for s in b.PLAYER_STATES
        }
        fields[vol.Required("fallback", default="off")] = _select(
            [_opt(s, s) for s in b.PLAYER_STATES] + [_opt("unknown", "unknown (show no state)")]
        )
        return self.async_show_form(
            step_id="value_state_map",
            data_schema=vol.Schema(fields),
            description_placeholders=self._ph(entity=entity),
        )

    async def async_step_value_active_when(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        children = list(self._current().get(CONF_CHILDREN) or [])
        if user_input is not None:
            states = [str(v) for v in user_input.get("states") or []]
            child_yes = user_input.get("child_yes")
            if states and child_yes:
                return await self._value_done(
                    b.tpl_active_child(
                        user_input["entity"],
                        states,
                        child_yes,
                        user_input.get("child_no") or None,
                    )
                )
        child_sel: Any = _select(children) if children else MEDIA_PLAYER
        return self.async_show_form(
            step_id="value_active_when",
            data_schema=vol.Schema(
                {
                    vol.Required("entity"): ANY_ENTITY,
                    vol.Required("states"): _select(
                        ["on", "off", "playing", "paused", "idle", "home", "not_home"],
                        multiple=True,
                        custom=True,
                    ),
                    vol.Required("child_yes"): child_sel,
                    vol.Optional("child_no"): child_sel,
                }
            ),
            description_placeholders=self._ph(label=self._target_label()),
        )

    async def async_step_value_fixed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._value_done(b.tpl_fixed(str(user_input["text"])))
        return self.async_show_form(
            step_id="value_fixed",
            data_schema=vol.Schema({vol.Required("text"): TEXT}),
            description_placeholders=self._ph(label=self._target_label()),
        )

    async def async_step_value_custom(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input, {"template": "template"})
            if not errors:
                return await self._value_done(user_input["template"])
        schema = vol.Schema({vol.Required("template"): TEMPLATE})
        suggested = user_input or {"template": self._target_get() or ""}
        return self.async_show_form(
            step_id="value_custom",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=self._ph(label=self._target_label()),
        )

    # ============================================================ custom attrs
    async def async_step_custom_attrs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="custom_attrs",
            menu_options=["custom_attr_add", "custom_attr_remove", "init"],
            description_placeholders=self._ph(
                count=len(self._current().get(CONF_CUSTOM_ATTRIBUTES) or {})
            ),
        )

    async def async_step_custom_attr_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        existing = list((self._current().get(CONF_CUSTOM_ATTRIBUTES) or {}))
        if user_input is not None:
            name = str(user_input["name"]).strip().replace(" ", "_").lower()
            if name:
                self._ctx = {"kind": "custom", "name": name, "back": "custom_attrs"}
                return await self.async_step_value_start()
        sel = _select(existing, custom=True) if existing else TEXT
        return self.async_show_form(
            step_id="custom_attr_add",
            data_schema=vol.Schema({vol.Required("name"): sel}),
            description_placeholders=self._ph(),
        )

    async def async_step_custom_attr_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._remove_names("custom_attr_remove", CONF_CUSTOM_ATTRIBUTES, "custom_attrs", user_input)

    # =========================================================================
    # ACTION WIZARD: services, sources, sound modes.
    # Ask "what should happen?" then write the actions for the user.
    # =========================================================================
    def _describe_steps(self, steps: list[Any]) -> str:
        lines = []
        for i, step in enumerate(steps, 1):
            if isinstance(step, dict) and "action" in step:
                target = (step.get("target") or {}).get("entity_id")
                lines.append(f"{i}. {step['action']}" + (f" on {target}" if target else ""))
            elif isinstance(step, dict) and "delay" in step:
                lines.append(f"{i}. wait")
            elif isinstance(step, dict) and "if" in step:
                lines.append(f"{i}. pass it on to the active child")
            else:
                lines.append(f"{i}. custom step")
        return "  \n".join(lines) if lines else "nothing yet"

    def _vars_text(self) -> str:
        names = list(self._ctx.get("vars") or []) + ["active_child"]
        return ", ".join(f"{n} ({b.VAR_HELP.get(n, '')})" for n in names)

    def _action_ph(self) -> dict[str, str]:
        return self._ph(
            label=self._ctx["label"],
            vars=self._vars_text(),
            count=len(self._ctx.get("steps") or []),
            current=self._describe_steps(self._ctx.get("steps") or []),
        )

    async def _start_actions(self, kind: str, name: str, back: str) -> ConfigFlowResult:
        bucket = {
            "service": CONF_SERVICE_SCRIPTS,
            "source": CONF_SOURCE_SCRIPTS,
            "sound_mode": CONF_SOUND_MODE_SCRIPTS,
        }[kind]
        if kind == "service":
            available = list(b.SERVICE_VARS.get(name, []))
            label = SERVICE_INFO[name][0]
        elif kind == "source":
            available, label = list(b.SOURCE_VARS), name
        else:
            available, label = list(b.SOUND_MODE_VARS), name
        existing = (self._current().get(bucket) or {}).get(name) or []
        self._ctx = {
            "kind": kind,
            "bucket": bucket,
            "name": name,
            "label": label,
            "back": back,
            "vars": available,
            "steps": list(existing),
            "existing": bool(existing),
        }
        if existing:
            return await self.async_step_actions_existing()
        return await self.async_step_action_type()

    def _store_steps(self) -> None:
        opts = self._current()
        bucket = dict(opts.get(self._ctx["bucket"]) or {})
        if self._ctx["steps"]:
            bucket[self._ctx["name"]] = list(self._ctx["steps"])
        else:
            bucket.pop(self._ctx["name"], None)
        if bucket:
            opts[self._ctx["bucket"]] = bucket
        else:
            opts.pop(self._ctx["bucket"], None)
        self._save()

    async def _step_added(self, step: Any) -> ConfigFlowResult:
        if isinstance(step, list):
            self._ctx["steps"].extend(step)
        else:
            self._ctx["steps"].append(step)
        self._store_steps()
        return await self.async_step_action_more()

    # -- pick which service to set up ----------------------------------------
    async def _pick_service(
        self, step_id: str, names: list[str], user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        configured = self._current().get(CONF_SERVICE_SCRIPTS) or {}
        if user_input is not None:
            choice = user_input["choice"]
            if choice == BACK:
                return await self.async_step_init()
            return await self._start_actions("service", choice, step_id)
        options = []
        for name in names:
            label, hint = SERVICE_INFO[name]
            mark = "✓ " if name in configured else ""
            options.append(_opt(name, f"{mark}{label}" + (f" ({hint})" if hint else "")))
        options.append(_opt(BACK, "← Back to the main menu"))
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required("choice"): _select(options, mode=LIST)}),
            description_placeholders=self._ph(),
        )

    async def async_step_actions_playback(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._pick_service("actions_playback", SERVICES_PLAYBACK, user_input)

    async def async_step_actions_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._pick_service("actions_power", SERVICES_POWER, user_input)

    async def async_step_actions_other(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._pick_service("actions_other", SERVICES_OTHER, user_input)

    # -- something is already set up -----------------------------------------
    async def async_step_actions_existing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="actions_existing",
            menu_options=[
                "action_replace",
                "action_add",
                "action_yaml_edit",
                "action_remove",
                "actions_done",
            ],
            description_placeholders=self._action_ph(),
        )

    async def async_step_action_replace(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._ctx["steps"] = []
        return await self.async_step_action_type()

    async def async_step_action_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_action_type()

    async def async_step_action_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._ctx["steps"] = []
        self._store_steps()
        return await self._goto(self._ctx["back"])

    async def async_step_action_yaml_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._ctx["yaml_replace"] = True
        return await self.async_step_action_yaml()

    async def async_step_actions_done(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._goto(self._ctx["back"])

    # -- what kind of step? --------------------------------------------------
    async def async_step_action_type(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._goto(user_input["type"])
        options = [
            _opt("action_forward", "Pass it on to another media player"),
            _opt("action_forward_active", "Pass it on to the active child"),
            _opt("action_call_entity", "Control a device (switch, button, light, script, scene, remote...)"),
            _opt("action_wait", "Wait a moment before the next step"),
            _opt("action_yaml", "Advanced: write the actions myself (YAML)"),
        ]
        return self.async_show_form(
            step_id="action_type",
            data_schema=vol.Schema({vol.Required("type"): _select(options, mode=LIST)}),
            description_placeholders=self._action_ph(),
        )

    # -- pass on to another media player -------------------------------------
    async def async_step_action_forward(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        kind = self._ctx["kind"]
        if user_input is not None:
            if kind == "service":
                service = self._ctx["name"]
            else:
                service = "select_source" if kind == "source" else "select_sound_mode"
            step = b.build_forward(
                service,
                user_input["entity"],
                self._ctx["vars"],
                (user_input.get("target_name") or "").strip() or None,
            )
            return await self._step_added(step)
        fields: dict[Any, Any] = {vol.Required("entity"): MEDIA_PLAYER}
        if kind in ("source", "sound_mode"):
            fields[vol.Optional("target_name")] = TEXT
        return self.async_show_form(
            step_id="action_forward",
            data_schema=vol.Schema(fields),
            description_placeholders=self._action_ph(),
        )

    async def async_step_action_forward_active(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        kind = self._ctx["kind"]
        if kind == "service":
            service = self._ctx["name"]
        else:
            service = "select_source" if kind == "source" else "select_sound_mode"
        step = b.build_forward_active(service, self._ctx["vars"])
        return await self._step_added(step)

    # -- control a device ----------------------------------------------------
    async def async_step_action_call_entity(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._ctx["call_entity"] = user_input["entity"]
            return await self.async_step_action_call_service()
        return self.async_show_form(
            step_id="action_call_entity",
            data_schema=vol.Schema({vol.Required("entity"): ANY_ENTITY}),
            description_placeholders=self._action_ph(),
        )

    async def async_step_action_call_service(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entity = self._ctx["call_entity"]
        domain = entity.split(".", 1)[0]
        if user_input is not None:
            service = str(user_input["service"]).strip()
            if "." not in service:
                service = f"{domain}.{service}"
            found = b.find_preset(service)
            fields = found[1] if found else []
            self._ctx["call_service"] = service
            self._ctx["call_fields"] = fields
            avail = self._ctx["vars"]
            if b.fields_to_ask(fields, avail) or b.wants_scale_option(fields, avail):
                return await self.async_step_action_call_fields()
            data = b.build_data(fields, avail, {})
            return await self._step_added(b.action_call(service, entity, data))
        options = [_opt(svc, label) for svc, label, _ in b.presets_for(domain)]
        return self.async_show_form(
            step_id="action_call_service",
            data_schema=vol.Schema({vol.Required("service"): _select(options, custom=True)}),
            description_placeholders=self._action_ph() | {"entity": entity},
        )

    async def async_step_action_call_fields(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        service = self._ctx["call_service"]
        fields = self._ctx["call_fields"]
        avail = self._ctx["vars"]
        if user_input is not None:
            data = b.build_data(fields, avail, user_input, bool(user_input.get("scale_100")))
            return await self._step_added(
                b.action_call(service, self._ctx["call_entity"], data)
            )

        schema: dict[Any, Any] = {}
        for field in b.fields_to_ask(fields, avail):
            kind = field["kind"]
            key = field["key"]
            required = not field.get("optional")
            if kind == "bool":
                schema[vol.Optional(key, default=bool(field.get("default", True)))] = BOOLEAN
                continue
            if kind == "number":
                sel: Any = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=field.get("min", 0),
                        max=field.get("max", 100),
                        step=field.get("step", 1),
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            elif kind == "select":
                sel = _select(field["options"])
            else:
                sel = TEXT
            schema[vol.Required(key) if required else vol.Optional(key)] = sel
        if b.wants_scale_option(fields, avail):
            schema[vol.Optional("scale_100", default=False)] = BOOLEAN
        return self.async_show_form(
            step_id="action_call_fields",
            data_schema=vol.Schema(schema),
            description_placeholders=self._action_ph() | {"entity": self._ctx["call_entity"]},
        )

    # -- wait ----------------------------------------------------------------
    async def async_step_action_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._step_added(b.action_delay(float(user_input["seconds"])))
        return self.async_show_form(
            step_id="action_wait",
            data_schema=vol.Schema(
                {
                    vol.Required("seconds", default=1): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1,
                            max=3600,
                            step=0.1,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
            description_placeholders=self._action_ph(),
        )

    # -- advanced: raw YAML --------------------------------------------------
    async def async_step_action_yaml(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        replace = bool(self._ctx.get("yaml_replace"))
        if user_input is not None:
            errors = self._validate(user_input, {"actions": "actions"})
            if not errors:
                new = user_input["actions"]
                new = new if isinstance(new, list) else [new]
                if replace:
                    self._ctx["steps"] = []
                    self._ctx["yaml_replace"] = False
                return await self._step_added(new)
        schema = vol.Schema({vol.Required("actions"): ACTIONS})
        suggested = user_input or ({"actions": self._ctx["steps"]} if replace else {})
        return self.async_show_form(
            step_id="action_yaml",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=self._action_ph(),
        )

    # -- after each step -----------------------------------------------------
    async def async_step_action_more(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="action_more",
            menu_options=["action_type", "actions_done"],
            description_placeholders=self._action_ph(),
        )

    # =========================================================================
    # SOURCES + SOUND MODES (a name, plus what happens when it is picked)
    # =========================================================================
    async def _named_menu(self, step_id: str) -> ConfigFlowResult:
        conf_key = CONF_SOURCE_SCRIPTS if step_id == "sources" else CONF_SOUND_MODE_SCRIPTS
        return self.async_show_menu(
            step_id=step_id,
            menu_options=[f"{step_id}_edit", f"{step_id}_remove", "init"],
            description_placeholders=self._ph(
                count=len(self._current().get(conf_key) or {})
            ),
        )

    async def _named_pick(
        self,
        step_id: str,
        kind: str,
        conf_key: str,
        list_attr: str,
        back: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        existing = list(self._current().get(conf_key) or {})
        if user_input is not None:
            name = str(user_input.get("name") or "").strip()
            if name:
                return await self._start_actions(kind, name, back)
        # offer what the children already know about, so nobody has to type
        suggestions: list[str] = []
        for child in self._current().get(CONF_CHILDREN) or []:
            state = self.hass.states.get(child)
            if state is None:
                continue
            for item in state.attributes.get(list_attr) or []:
                if str(item) not in suggestions:
                    suggestions.append(str(item))
        options = [_opt(n, f"✓ {n}") for n in existing]
        options += [_opt(s, s) for s in suggestions if s not in existing]
        sel: Any = _select(options, custom=True) if options else TEXT
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required("name"): sel}),
            description_placeholders=self._ph(),
        )

    async def _remove_names(
        self, step_id: str, conf_key: str, back: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        opts = self._current()
        existing = list(opts.get(conf_key) or {})
        if not existing:
            return await self._goto(back)
        if user_input is not None:
            items = dict(opts.get(conf_key) or {})
            for name in user_input.get("names", []):
                items.pop(name, None)
            if items:
                opts[conf_key] = items
            else:
                opts.pop(conf_key, None)
            self._save()
            return await self._goto(back)
        schema = vol.Schema(
            {vol.Required("names"): _select(existing, multiple=True, mode=LIST)}
        )
        return self.async_show_form(
            step_id=step_id, data_schema=schema, description_placeholders=self._ph()
        )

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._named_menu("sources")

    async def async_step_sources_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._named_pick(
            "sources_edit", "source", CONF_SOURCE_SCRIPTS, "source_list", "sources", user_input
        )

    async def async_step_sources_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._remove_names("sources_remove", CONF_SOURCE_SCRIPTS, "sources", user_input)

    async def async_step_sound_modes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._named_menu("sound_modes")

    async def async_step_sound_modes_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._named_pick(
            "sound_modes_edit",
            "sound_mode",
            CONF_SOUND_MODE_SCRIPTS,
            "sound_mode_list",
            "sound_modes",
            user_input,
        )

    async def async_step_sound_modes_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._remove_names(
            "sound_modes_remove", CONF_SOUND_MODE_SCRIPTS, "sound_modes", user_input
        )

    # =========================================================================
    # ADVANCED: the original free-form pages (templates + YAML)
    # =========================================================================
    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="advanced",
            menu_options=[
                "adv_general",
                "adv_attributes_media",
                "adv_attributes_player",
                "adv_custom_attributes",
                "adv_services_playback",
                "adv_services_power",
                "adv_services_other",
                "init",
            ],
            description_placeholders=self._ph(),
        )

    async def async_step_adv_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_general",
            {
                CONF_STATE: TEMPLATE,
                CONF_ACTIVE_CHILD: TEMPLATE,
            },
            None,
            user_input,
            {
                CONF_STATE: "template",
                CONF_ACTIVE_CHILD: "template",
            },
            back="advanced",
        )

    async def async_step_adv_attributes_media(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_attributes_media",
            {n: TEMPLATE for n in ATTRIBUTES_MEDIA},
            CONF_ATTRIBUTES,
            user_input,
            {n: "template" for n in ATTRIBUTES_MEDIA},
            back="advanced",
        )

    async def async_step_adv_attributes_player(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_attributes_player",
            {n: TEMPLATE for n in ATTRIBUTES_PLAYER},
            CONF_ATTRIBUTES,
            user_input,
            {n: "template" for n in ATTRIBUTES_PLAYER},
            back="advanced",
        )

    async def async_step_adv_custom_attributes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_custom_attributes",
            {CONF_CUSTOM_ATTRIBUTES: OBJECT},
            None,
            user_input,
            {CONF_CUSTOM_ATTRIBUTES: "templates_dict"},
            back="advanced",
        )

    async def async_step_adv_services_playback(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_services_playback",
            {n: ACTIONS for n in SERVICES_PLAYBACK},
            CONF_SERVICE_SCRIPTS,
            user_input,
            {n: "actions" for n in SERVICES_PLAYBACK},
            back="advanced",
        )

    async def async_step_adv_services_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_services_power",
            {n: ACTIONS for n in SERVICES_POWER},
            CONF_SERVICE_SCRIPTS,
            user_input,
            {n: "actions" for n in SERVICES_POWER},
            back="advanced",
        )

    async def async_step_adv_services_other(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._group_step(
            "adv_services_other",
            {n: ACTIONS for n in SERVICES_OTHER},
            CONF_SERVICE_SCRIPTS,
            user_input,
            {n: "actions" for n in SERVICES_OTHER},
            back="advanced",
        )
