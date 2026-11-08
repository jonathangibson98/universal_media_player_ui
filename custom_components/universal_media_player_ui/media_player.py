"""Universal media player entity (configured entirely from the UI).

Behaves like Home Assistant's built-in universal media player:

* it follows the first *active* child (a child that is not off / idle / unavailable)
* the optional State setting can force it off, or keep it on with no child playing
* anything you override (attributes, buttons) is used; everything else comes from,
  or is passed on to, the active child
"""
from __future__ import annotations

import ast
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    TrackTemplate,
    async_track_state_change_event,
    async_track_template_result,
)
from homeassistant.helpers.script import SCRIPT_MODE_PARALLEL, Script
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from . import builders as b
from .const import (
    ALL_ATTRIBUTES,
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
    EXTRA_ONLY_ATTRIBUTES,
    FLOAT_ATTRIBUTES,
    INT_ATTRIBUTES,
    LIST_ATTRIBUTES,
)

_LOGGER = logging.getLogger(__name__)

F = MediaPlayerEntityFeature

# Which feature flag each configured action switches on
FEATURE_MAP: dict[str, MediaPlayerEntityFeature] = {
    "turn_on": F.TURN_ON,
    "turn_off": F.TURN_OFF,
    "toggle": F.TURN_ON | F.TURN_OFF,
    "media_play": F.PLAY,
    "media_pause": F.PAUSE,
    "media_stop": F.STOP,
    "media_play_pause": F.PLAY | F.PAUSE,
    "media_next_track": F.NEXT_TRACK,
    "media_previous_track": F.PREVIOUS_TRACK,
    "media_seek": F.SEEK,
    "volume_set": F.VOLUME_SET,
    "volume_mute": F.VOLUME_MUTE,
    "volume_up": F.VOLUME_STEP,
    "volume_down": F.VOLUME_STEP,
    "shuffle_set": F.SHUFFLE_SET,
    "repeat_set": F.REPEAT_SET,
    "play_media": F.PLAY_MEDIA,
    "clear_playlist": F.CLEAR_PLAYLIST,
    "join": F.GROUPING,
    "unjoin": F.GROUPING,
    "select_source": F.SELECT_SOURCE,
    "select_sound_mode": F.SELECT_SOUND_MODE,
}

NONE_STRINGS = {"", "none", "unknown", "unavailable", "null"}

# Attributes that MediaPlayerEntity supports natively through _attr_<name>
ENTITY_ATTRS = [
    a
    for a in ALL_ATTRIBUTES
    if a != "entity_picture" and a not in EXTRA_ONLY_ATTRIBUTES
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the media player for this config entry."""
    async_add_entities([UniversalMediaPlayer(hass, entry)])


def _clean(value: Any) -> Any:
    """Turn 'none', 'unknown' and friends into None."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped.lower() in NONE_STRINGS else stripped
    return value


def _to_list(value: Any) -> list[str] | None:
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
            return [str(v) for v in parsed]
        except (ValueError, SyntaxError):
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _coerce(name: str, value: Any) -> Any:
    """Convert a rendered value to the type the entity expects."""
    if value is None:
        return None
    try:
        if name in INT_ATTRIBUTES:
            return int(float(value))
        if name in FLOAT_ATTRIBUTES:
            return float(value)
        if name in BOOL_ATTRIBUTES:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "on", "yes", "1")
        if name == "media_position_updated_at":
            if isinstance(value, datetime):
                return value
            return dt_util.parse_datetime(str(value))
        if name == "repeat":
            return RepeatMode(str(value).strip().lower())
        if name in LIST_ATTRIBUTES:
            return _to_list(value)
        return str(value)
    except (ValueError, TypeError):
        _LOGGER.warning("Could not convert %r to a valid value for %s", value, name)
        return None


class UniversalMediaPlayer(MediaPlayerEntity):
    """A media player that combines child players and other entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._cfg: dict[str, Any] = dict(entry.options)

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title
        )
        if icon := self._cfg.get(CONF_ICON):
            self._attr_icon = icon
        if dc := self._cfg.get(CONF_DEVICE_CLASS):
            try:
                self._attr_device_class = MediaPlayerDeviceClass(dc)
            except ValueError:
                _LOGGER.warning("Unknown device class %s", dc)

        self._children: list[str] = list(self._cfg.get(CONF_CHILDREN) or [])
        self._browse_target: str | None = self._cfg.get(CONF_BROWSE) or None
        self._search_target: str | None = self._cfg.get(CONF_SEARCH) or None

        self._state_tpl: Template | None = None
        self._active_tpl: Template | None = None
        self._attr_tpls: dict[str, Template] = {}
        self._custom_tpls: dict[str, Template] = {}
        self._scripts: dict[str, Script] = {}
        self._source_scripts: dict[str, Script] = {}
        self._sound_scripts: dict[str, Script] = {}
        self._features = MediaPlayerEntityFeature(0)

        self._child: State | None = None
        self._picture: str | None = None
        self._extra: dict[str, Any] = {}
        self._last_pos: Any = None
        self._last_pos_stamp: datetime | None = None

    # ------------------------------------------------------------------ setup
    async def async_added_to_hass(self) -> None:
        """Build templates + scripts, start tracking, do the first render."""
        self._build_templates()
        self._build_scripts()
        self._features = self._compute_features()
        self._start_tracking()
        self._refresh()

    def _build_templates(self) -> None:
        if src := self._cfg.get(CONF_STATE):
            self._state_tpl = Template(src, self.hass)
        if src := self._cfg.get(CONF_ACTIVE_CHILD):
            self._active_tpl = Template(src, self.hass)
        for name, src in (self._cfg.get(CONF_ATTRIBUTES) or {}).items():
            if src:
                self._attr_tpls[name] = Template(str(src), self.hass)
        for name, src in (self._cfg.get(CONF_CUSTOM_ATTRIBUTES) or {}).items():
            self._custom_tpls[name] = Template(str(src), self.hass)

    def _make_script(self, label: str, actions: Any) -> Script | None:
        try:
            sequence = cv.SCRIPT_SCHEMA(actions)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Invalid actions for %s: %s", label, err)
            return None
        return Script(
            self.hass,
            sequence,
            f"{self._entry.title} {label}",
            DOMAIN,
            script_mode=SCRIPT_MODE_PARALLEL,
            max_runs=10,
        )

    def _build_scripts(self) -> None:
        for key, actions in (self._cfg.get(CONF_SERVICE_SCRIPTS) or {}).items():
            if script := self._make_script(key, actions):
                self._scripts[key] = script
        for key, actions in (self._cfg.get(CONF_SOURCE_SCRIPTS) or {}).items():
            if script := self._make_script(f"source {key}", actions):
                self._source_scripts[key] = script
        for key, actions in (self._cfg.get(CONF_SOUND_MODE_SCRIPTS) or {}).items():
            if script := self._make_script(f"sound mode {key}", actions):
                self._sound_scripts[key] = script

    def _compute_features(self) -> MediaPlayerEntityFeature:
        features = MediaPlayerEntityFeature(0)
        for key in self._scripts:
            features |= FEATURE_MAP.get(key, MediaPlayerEntityFeature(0))
        if self._source_scripts:
            features |= F.SELECT_SOURCE
        if self._sound_scripts:
            features |= F.SELECT_SOUND_MODE
        if self._browse_target:
            features |= F.BROWSE_MEDIA
        if self._search_target and hasattr(F, "SEARCH_MEDIA"):
            features |= F.SEARCH_MEDIA
        return features

    def _start_tracking(self) -> None:
        """Re-render whenever a child, or any entity used by a template, changes."""
        tracked: list[TrackTemplate] = []

        def add(tpl: Template | None) -> None:
            if tpl is None or getattr(tpl, "is_static", False):
                return
            tracked.append(TrackTemplate(tpl, {}))

        add(self._state_tpl)
        add(self._active_tpl)
        for tpl in self._attr_tpls.values():
            add(tpl)
        for tpl in self._custom_tpls.values():
            add(tpl)

        if tracked:
            info = async_track_template_result(
                self.hass, tracked, self._template_updated
            )
            self.async_on_remove(info.async_remove)

        if self._children:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, self._children, self._child_changed
                )
            )

    @callback
    def _template_updated(self, event: Event | None, updates: list) -> None:
        self._refresh()
        self.async_write_ha_state()

    @callback
    def _child_changed(self, event: Event) -> None:
        self._refresh()
        self.async_write_ha_state()

    # --------------------------------------------------------------- rendering
    def _render(self, tpl: Template | None) -> Any:
        if tpl is None:
            return None
        try:
            result = tpl.async_render(parse_result=False)
        except TemplateError as err:
            _LOGGER.warning("Template error in %s: %s", self.entity_id, err)
            return None
        return _clean(result)

    def _find_active_child(self) -> State | None:
        """The child to follow: your override, else the first one that is not off/idle."""
        if self._active_tpl is not None:
            override = self._render(self._active_tpl)
            if override:
                state = self.hass.states.get(str(override).strip())
                if state is not None:
                    return state
        return b.pick_active_child(self._children, self.hass.states.get)

    @callback
    def _refresh(self) -> None:
        """Re-render everything and push the values onto the entity."""
        child = self._find_active_child()
        self._child = child
        self._attr_available = True

        # state
        master = self._render(self._state_tpl) if self._state_tpl is not None else None
        if master is not None and str(master).strip().lower() not in b.VALID_STATES:
            _LOGGER.warning(
                "%s: the State setting gave %r - must be one of %s",
                self.entity_id,
                master,
                ", ".join(b.VALID_STATES),
            )
        resolved = b.resolve_state(
            self._state_tpl is not None,
            None if master is None else str(master),
            child.state if child is not None else None,
        )
        try:
            self._attr_state = MediaPlayerState(resolved)
        except ValueError:
            _LOGGER.debug("%s: child state %r is not a media player state", self.entity_id, resolved)
            self._attr_state = MediaPlayerState.ON

        # attributes: your override, else the active child's value
        picture_overridden = "media_image_url" in self._attr_tpls
        values: dict[str, Any] = {}
        for name in ALL_ATTRIBUTES:
            tpl = self._attr_tpls.get(name)
            if tpl is not None:
                raw = self._render(tpl)
            elif child is not None and not (name == "entity_picture" and picture_overridden):
                raw = _clean(child.attributes.get(name))
            else:
                raw = None
            values[name] = _coerce(name, raw)

        # media_position needs a timestamp, otherwise HA ignores it
        if values["media_position"] is not None and values["media_position_updated_at"] is None:
            if values["media_position"] != self._last_pos or self._last_pos_stamp is None:
                self._last_pos_stamp = dt_util.utcnow()
            values["media_position_updated_at"] = self._last_pos_stamp
        self._last_pos = values["media_position"]

        extra: dict[str, Any] = {}
        for name, value in values.items():
            if name in ENTITY_ATTRS:
                setattr(self, f"_attr_{name}", value)
            elif name == "entity_picture":
                self._picture = value
            elif value is not None:
                extra[name] = value

        # sources / sound modes you named yourself replace the lists, unless you set a list
        if "source_list" not in self._attr_tpls and self._source_scripts:
            self._attr_source_list = list(self._source_scripts)
        if "sound_mode_list" not in self._attr_tpls and self._sound_scripts:
            self._attr_sound_mode_list = list(self._sound_scripts)

        # custom attributes (anything you want)
        for name, tpl in self._custom_tpls.items():
            extra[name] = self._render(tpl)
        if child is not None:
            extra["active_child"] = child.entity_id
        self._extra = extra

    # -------------------------------------------------------------- properties
    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = self._features
        if self._child is not None:
            try:
                features |= MediaPlayerEntityFeature(
                    int(self._child.attributes.get("supported_features", 0))
                )
            except (ValueError, TypeError):
                pass
        return features

    @property
    def entity_picture(self) -> str | None:
        if self._picture:
            return self._picture
        return super().entity_picture

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._extra or None

    # ----------------------------------------------------------------- actions
    @property
    def _child_id(self) -> str | None:
        return self._child.entity_id if self._child is not None else None

    async def _forward(self, service: str, data: dict[str, Any]) -> None:
        """Pass a call through to the active child."""
        await self.hass.services.async_call(
            "media_player",
            service,
            {"entity_id": self._child_id, **data},
            blocking=True,
            context=self._context,
        )

    async def _run(self, script: Script, run_vars: dict[str, Any] | None) -> None:
        await script.async_run(
            run_variables={**(run_vars or {}), "active_child": self._child_id},
            context=self._context,
        )

    async def _dispatch(
        self,
        service: str,
        run_vars: dict[str, Any] | None = None,
        child_data: dict[str, Any] | None = None,
        fallback: Any = None,
    ) -> None:
        """Run your steps, else pass to the active child, else fall back."""
        script = self._scripts.get(service)
        if script is not None:
            await self._run(script, run_vars)
        elif self._child is not None:
            await self._forward(service, child_data or {})
        elif fallback is not None:
            await fallback()
        else:
            _LOGGER.debug("%s: nothing to do for %s (no steps set up and no active child)", self.entity_id, service)

    async def async_turn_on(self) -> None:
        await self._dispatch("turn_on")

    async def async_turn_off(self) -> None:
        await self._dispatch("turn_off")

    async def async_toggle(self) -> None:
        if "toggle" in self._scripts:
            await self._run(self._scripts["toggle"], None)
        elif "turn_on" in self._scripts and "turn_off" in self._scripts:
            if self.state == MediaPlayerState.OFF:
                await self.async_turn_on()
            else:
                await self.async_turn_off()
        else:
            await self._dispatch("toggle", fallback=super().async_toggle)

    async def async_media_play(self) -> None:
        await self._dispatch("media_play")

    async def async_media_pause(self) -> None:
        await self._dispatch("media_pause")

    async def async_media_stop(self) -> None:
        await self._dispatch("media_stop")

    async def async_media_play_pause(self) -> None:
        await self._dispatch("media_play_pause", fallback=super().async_media_play_pause)

    async def async_media_next_track(self) -> None:
        await self._dispatch("media_next_track")

    async def async_media_previous_track(self) -> None:
        await self._dispatch("media_previous_track")

    async def async_media_seek(self, position: float) -> None:
        await self._dispatch(
            "media_seek",
            {"position": position, "seek_position": position},
            {"seek_position": position},
        )

    async def async_set_volume_level(self, volume: float) -> None:
        await self._dispatch(
            "volume_set",
            {"volume": volume, "volume_level": volume},
            {"volume_level": volume},
        )

    async def async_mute_volume(self, mute: bool) -> None:
        await self._dispatch(
            "volume_mute",
            {"mute": mute, "is_volume_muted": mute},
            {"is_volume_muted": mute},
        )

    async def async_volume_up(self) -> None:
        await self._dispatch("volume_up", fallback=super().async_volume_up)

    async def async_volume_down(self) -> None:
        await self._dispatch("volume_down", fallback=super().async_volume_down)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        value = str(repeat.value if hasattr(repeat, "value") else repeat)
        await self._dispatch("repeat_set", {"repeat": value}, {"repeat": value})

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._dispatch("shuffle_set", {"shuffle": shuffle}, {"shuffle": shuffle})

    async def async_clear_playlist(self) -> None:
        await self._dispatch("clear_playlist")

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        extras = {
            k: v for k, v in kwargs.items() if k in ("announce", "enqueue", "extra")
        }
        await self._dispatch(
            "play_media",
            {
                "media_type": media_type,
                "media_id": media_id,
                "media_content_type": media_type,
                "media_content_id": media_id,
                **extras,
            },
            {"media_content_type": media_type, "media_content_id": media_id, **extras},
        )

    async def async_join_players(self, group_members: list[str]) -> None:
        await self._dispatch(
            "join", {"group_members": group_members}, {"group_members": group_members}
        )

    async def async_unjoin_player(self) -> None:
        await self._dispatch("unjoin")

    async def async_select_source(self, source: str) -> None:
        script = self._source_scripts.get(source)
        if script is not None:
            await self._run(script, {"source": source})
        else:
            await self._dispatch("select_source", {"source": source}, {"source": source})

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        script = self._sound_scripts.get(sound_mode)
        if script is not None:
            await self._run(script, {"sound_mode": sound_mode})
        else:
            await self._dispatch(
                "select_sound_mode", {"sound_mode": sound_mode}, {"sound_mode": sound_mode}
            )

    # ------------------------------------------------------- browse + search
    def _browse_entity(self, explicit: str | None) -> str | None:
        """Your chosen player, else the active child, else the first child."""
        return explicit or self._child_id or (self._children[0] if self._children else None)

    def _delegate(self, entity_id: str | None) -> MediaPlayerEntity:
        component = self.hass.data.get("media_player")
        entity = component.get_entity(entity_id) if component and entity_id else None
        if entity is None:
            raise HomeAssistantError(f"Media player {entity_id} is not available")
        return entity

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ):
        target = self._browse_entity(self._browse_target)
        if not target:
            return await super().async_browse_media(media_content_type, media_content_id)
        return await self._delegate(target).async_browse_media(
            media_content_type, media_content_id
        )

    async def async_search_media(self, query):
        target = self._browse_entity(self._search_target)
        if not target:
            raise NotImplementedError
        return await self._delegate(target).async_search_media(query)
