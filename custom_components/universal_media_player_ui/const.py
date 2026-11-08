"""Constants for Universal Media Player (UI)."""
from __future__ import annotations

DOMAIN = "universal_media_player_ui"

CONF_DEVICE_CLASS = "device_class"
CONF_ICON = "icon"
CONF_CHILDREN = "children"
CONF_ACTIVE_CHILD = "active_child_template"
CONF_BROWSE = "browse_media_entity_id"
CONF_SEARCH = "search_media_entity_id"
CONF_STATE = "state"
CONF_ATTRIBUTES = "attributes"
CONF_CUSTOM_ATTRIBUTES = "custom_attributes"
CONF_SERVICE_SCRIPTS = "service_scripts"
CONF_SOURCE_SCRIPTS = "source_scripts"
CONF_SOUND_MODE_SCRIPTS = "sound_mode_scripts"

# Attribute templates, split into two UI pages
ATTRIBUTES_MEDIA = [
    "media_title",
    "media_artist",
    "media_album_name",
    "media_album_artist",
    "media_series_title",
    "media_season",
    "media_episode",
    "media_channel",
    "media_playlist",
    "media_track",
    "media_content_id",
    "media_content_type",
    "media_duration",
    "media_position",
    "media_position_updated_at",
    "media_image_url",
    "media_image_remotely_accessible",
    "entity_picture",
    "app_id",
    "app_name",
    "media_content_rating",
    "media_summary",
]
ATTRIBUTES_PLAYER = [
    "volume_level",
    "is_volume_muted",
    "source",
    "source_list",
    "sound_mode",
    "sound_mode_list",
    "shuffle",
    "repeat",
    "group_members",
]
ALL_ATTRIBUTES = ATTRIBUTES_MEDIA + ATTRIBUTES_PLAYER

# Type coercion for rendered template output
INT_ATTRIBUTES = {"media_duration", "media_position", "media_track"}
FLOAT_ATTRIBUTES = {"volume_level"}
BOOL_ATTRIBUTES = {"is_volume_muted", "shuffle", "media_image_remotely_accessible"}
LIST_ATTRIBUTES = {"source_list", "sound_mode_list", "group_members"}
# These have no native MediaPlayerEntity property, so they show up as plain state attributes
EXTRA_ONLY_ATTRIBUTES = {"media_content_rating", "media_summary"}

# Action (script) pages, split into three UI pages
SERVICES_PLAYBACK = [
    "media_play",
    "media_pause",
    "media_stop",
    "media_play_pause",
    "media_next_track",
    "media_previous_track",
    "media_seek",
]
SERVICES_POWER = [
    "turn_on",
    "turn_off",
    "toggle",
    "volume_up",
    "volume_down",
    "volume_mute",
    "volume_set",
]
SERVICES_OTHER = [
    "repeat_set",
    "shuffle_set",
    "play_media",
    "clear_playlist",
    "join",
    "unjoin",
    "select_source",
    "select_sound_mode",
]
ALL_SERVICES = SERVICES_PLAYBACK + SERVICES_POWER + SERVICES_OTHER

# ---------------------------------------------------------------------------
# Friendly names shown in the pick lists: name -> (label, what it does)
# ---------------------------------------------------------------------------
ATTRIBUTE_INFO: dict[str, tuple[str, str]] = {
    "media_title": ("Title", "what is playing"),
    "media_artist": ("Artist", "who is performing"),
    "media_album_name": ("Album", "album name"),
    "media_album_artist": ("Album artist", "artist of the album"),
    "media_series_title": ("Series title", "TV show name"),
    "media_season": ("Season", "season number"),
    "media_episode": ("Episode", "episode number"),
    "media_channel": ("Channel", "TV or radio channel"),
    "media_playlist": ("Playlist", "current playlist"),
    "media_track": ("Track number", "position in the album/playlist"),
    "media_content_id": ("Content ID", "internal id of what is playing"),
    "media_content_type": ("Content type", "music, movie, tvshow, channel..."),
    "media_duration": ("Duration", "total length in seconds"),
    "media_position": ("Position", "seconds played so far"),
    "media_position_updated_at": ("Position updated at", "when the position was measured"),
    "media_image_url": ("Image URL", "cover art address"),
    "media_image_remotely_accessible": ("Image is remotely accessible", "yes/no"),
    "entity_picture": ("Entity picture", "cover art shown on the card"),
    "app_id": ("App ID", "id of the running app"),
    "app_name": ("App name", "name of the running app"),
    "media_content_rating": ("Content rating", "e.g. PG-13"),
    "media_summary": ("Summary", "description of what is playing"),
    "volume_level": ("Volume level", "0 to 1"),
    "is_volume_muted": ("Muted", "yes/no"),
    "source": ("Current source", "selected input"),
    "source_list": ("Source list", "all the inputs you can pick from"),
    "sound_mode": ("Current sound mode", "selected sound mode"),
    "sound_mode_list": ("Sound mode list", "all the sound modes you can pick from"),
    "shuffle": ("Shuffle", "yes/no"),
    "repeat": ("Repeat", "off, all or one"),
    "group_members": ("Group members", "players grouped with this one"),
}

SERVICE_INFO: dict[str, tuple[str, str]] = {
    "media_play": ("Play", ""),
    "media_pause": ("Pause", ""),
    "media_stop": ("Stop", ""),
    "media_play_pause": ("Play / pause", "toggle button"),
    "media_next_track": ("Next track", ""),
    "media_previous_track": ("Previous track", ""),
    "media_seek": ("Seek", "jump to a position"),
    "turn_on": ("Turn on", ""),
    "turn_off": ("Turn off", ""),
    "toggle": ("Toggle power", ""),
    "volume_up": ("Volume up", ""),
    "volume_down": ("Volume down", ""),
    "volume_mute": ("Mute / unmute", ""),
    "volume_set": ("Set volume", "slider"),
    "repeat_set": ("Set repeat", ""),
    "shuffle_set": ("Set shuffle", ""),
    "play_media": ("Play media", "from the media browser"),
    "clear_playlist": ("Clear playlist", ""),
    "join": ("Join group", ""),
    "unjoin": ("Leave group", ""),
    "select_source": ("Pick a source", "runs for any source that has no steps of its own"),
    "select_sound_mode": ("Pick a sound mode", "runs for any sound mode that has no steps of its own"),
}

# Picking an item from a list that means "go back"
BACK = "__back__"
