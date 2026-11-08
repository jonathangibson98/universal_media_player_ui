# Universal Media Player (UI)

[![Open your Home Assistant instance and open Universal Media Player (UI) inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jonathangibson98&repository=universal-media-player-ui&category=integration)

Home Assistant's [universal media player](https://www.home-assistant.io/integrations/universal)
rebuilt as a custom integration you set up by **pointing and clicking**. No YAML and no
templates to write: you pick children, entities and actions from lists and the integration
does the rest.

It follows the same rules as the built-in universal player, and uses the same menus as
[Template Media Player (UI)](https://github.com/jonathangibson98/template-media-player-ui).

> It lives in its own domain (`universal_media_player_ui`), so it never touches the built-in
> `universal` platform. Any universal players you already have in `configuration.yaml` keep working.

## Install
[![Open your Home Assistant instance and open Universal Media Player (UI) inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jonathangibson98&repository=universal-media-player-ui&category=integration)

Or by hand:

1. Copy the `universal_media_player_ui` folder into `<your HA config>/custom_components/`
   (the same folder that has `configuration.yaml`), or add this repository to HACS as a custom repository.
2. Restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> "Universal Media Player (UI)".

## Set it up
Settings -> Devices & services -> Universal Media Player (UI) -> your player -> gear icon (Configure).
Everything saves as you go. Choose **Save & close** when you're done.

| YAML option | Where it is in the UI |
|---|---|
| `name` | When you add the player |
| `children` | **Basics -> Children** (put them in order) |
| `device_class` | **Basics** |
| `browse_media_entity` | **Basics -> Media browser from** |
| `state_template` / `attributes: state` | **State**: follow an entity's state, an attribute, or say which of its states mean on, off, playing... |
| `active_child_template` | **Active child**: switch child depending on another entity's state, or write a template |
| `attributes:` (`volume_level`, `is_volume_muted`, `source`, `source_list`, `sound_mode`, `sound_mode_list`...) | **What's playing** / **Player info**: pick an item, then choose where its value comes from (an entity's state, one of its attributes picked from a list, a fixed value, or "yes while an entity is in these states") |
| any other attribute (for example `sound_mode_raw`) | **Extra attributes** |
| `commands:` (`turn_on`, `volume_up`, `volume_set`, `select_source`...) | **Buttons** menus: pick a button, then choose what happens: pass it to another media player, pass it to the active child, control a device (switch, button, light, script, scene, remote...) from a list of actions, wait a moment, and chain as many steps as you like |
| (new) one set of steps per source or sound mode | **Sources** / **Sound modes** |
| the YAML itself | **Advanced**: template and YAML pages, if you ever want them. Anything set there shows up in the simple menus too |

A ✓ in a list means that item is already set up.

## How it behaves (same as the built-in player)
* The player follows the **first child that is not off, idle or unavailable**. Use **Active child** to override that.
* Anything you leave empty is taken from the active child, and any button you don't set up is passed on to it.
* **State**: if you set it and it says *off*, the player is off, whatever the children do. If it says *on* and no child is playing, the player is on. If you don't set it, the player simply shows the active child's state (or *off* when none is active).
* Supported features (the buttons on the media card) are the active child's, plus every button you set up.
* Media browsing and search use the player you pick in **Basics**, otherwise the active child, otherwise the first child.

## Examples
These are the examples from the Home Assistant documentation, done in the UI.

**Chromecast and Kodi, TV power on a switch, volume on a receiver**
1. **Basics -> Children**: the Chromecast, then the Kodi player.
2. **State**: *Use the state of an entity* -> `switch.living_room_tv`.
3. **Buttons: power and volume**: Turn on -> *Control a device* -> `switch.living_room_tv` -> Turn on. Turn off likewise.
   Set volume -> *Pass it on to another media player* -> `media_player.receiver`.
4. **Player info**: Volume level -> *Use one attribute of an entity* -> `media_player.receiver` -> `volume_level`.
   Current source and Source list likewise (`source`, `source_list`).
5. **Buttons: repeat, shuffle...**: Pick a source -> *Pass it on to another media player* -> `media_player.receiver`.

**Harmony remote**
1. **State**: *Use the state of an entity* -> `remote.harmony_hub`.
2. **Player info**: Source list -> attribute `activity_list`; Current source -> attribute `current_activity`.
3. **Buttons**: Turn on / Turn off -> *Control a device* -> `remote.harmony_hub`. Volume up -> *Control a device* -> `remote.harmony_hub` -> *Send a remote command* (device `Receiver`, command `VolumeUp`).
   Pick a source -> *Control a device* -> `remote.harmony_hub` -> Turn on, with the `activity` set to `{{ source }}` (use the YAML step for this one).

**Denon AVR and HEOS**
Children: the Denon AVR and the HEOS player. Basics -> Media browser from: the HEOS player.
Turn on/off and volume up/down -> pass on to the Denon player. Sound mode, sound mode list -> attributes of the Denon player.
Pick a sound mode -> pass on to the Denon player.

**Override active child**
The point-and-click option under **Active child** picks a child from another entity's *state*
(for example "use the Sony PSK child while `sensor.tv_app` is `TV`, otherwise the Cast child").
The documentation example checks an *attribute* (`app_name`), so for that one choose
*Advanced: write a template myself* and paste the template from the documentation.

## Extras compared with the YAML version
* `active_child` is shown as an attribute on the player, and is available to your steps as `{{ active_child }}`.
* **Pass it on to the active child** is a step you can chain with others (for example: turn on a switch, wait, then press play on whichever child is active).
* Sources and sound modes can each have their own steps, on top of the single "Pick a source" button.
* Values you pass to a step are available under both the universal player's names (`volume_level`, `is_volume_muted`, `seek_position`, `media_content_id`...) and short names (`volume`, `mute`, `position`, `media_id`...).

## Notes
* Players you create here are separate from YAML universal players. There is no import; set them up again in the UI.
* If the State setting gives something that is not a media player state (on, off, idle, playing, paused, standby, buffering), the player shows as off and a warning is logged.

## Help
Questions or problems? Open an issue at
<https://github.com/jonathangibson98/universal-media-player-ui/issues>.
