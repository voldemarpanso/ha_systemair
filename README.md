# Systemair SAVE Connect Integration for Home Assistant (non-official)

[![GitHub Release](https://img.shields.io/github/v/release/voldemarpanso/ha_systemair)](https://github.com/voldemarpanso/ha_systemair/)[![Downloads](https://img.shields.io/github/downloads/voldemarpanso/ha_systemair/total)](https://github.com/voldemarpanso/ha_systemair/releases)[![GitHub Last Commit](https://img.shields.io/github/last-commit/voldemarpanso/ha_systemair)](https://github.com/voldemarpanso/ha_systemair/)[![HA Badge](https://img.shields.io/badge/Home%20Assistant-%23FFFFFF?logo=homeassistant)](https://www.home-assistant.io/)[![HACS Badge](https://img.shields.io/badge/Custom-%2341BDF5?label=HACS)](https://hacs.xyz/docs/faq/custom_repositories/)[![Static Badge](https://img.shields.io/badge/Buy%20me%20a%20beer-white?logo=paypal&label=Paypal)](https://www.paypal.com/donate/?business=KRHMM8QBFCVJ2&no_recurring=0&item_name=Buy+me+a+beer&currency_code=EUR)

Custom integration for Systemair ventilation units with an IAM module, using
the SAVE Connect / Home Solutions cloud (`homesolutions.systemair.com`).

## Credits

Based on [perara/ha_systemair](https://github.com/perara/ha_systemair) and the
SAVE Connect library
[perara/python-systemair-saveconnect](https://github.com/perara/python-systemair-saveconnect)
by @perara, since rewritten for current Home Assistant and the SAVE Connect API.

## Disclaimer

To be honest, I have been using this integration for years and have fixed it
several times, because Systemair's GraphQL API has changed at least twice, and
I believe the authentication method changed too. Unfortunately, I never had
enough time to polish it for public use. Now, with the help of modern assistants, 
I have cleaned it up and finished it to the point where I feel others can benefit 
from it too. And yes, I know there is another fairly recent project offering 
similar features - good work!

## Screenshots

<p>
  <img src="https://raw.githubusercontent.com/voldemarpanso/ha_systemair/master/images/hvac_control.png" alt="Climate control card">
  <img src="https://raw.githubusercontent.com/voldemarpanso/ha_systemair/master/images/sensor_cards.png" alt="Sensor and function cards">
</p>

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=voldemarpanso&repository=ha_systemair&category=integration)
- or add custom repo manually in HACS: https://github.com/voldemarpanso/ha_systemair
- or copy `custom_components/systemair` from the latest release into `config/custom_components/`

Download **Systemair SAVE Connect** and restart Home Assistant. Requires Home
Assistant 2024.11 or newer.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=systemair)
- or go to Settings -> Devices & Services and add **Systemair SAVE Connect**

Log in with your Home Solutions account.

## Features

- **Climate**: target temperature and presets (Auto, Manual, Crowded, Refresh,
  Fireplace, Away, Holiday). The fan level can be set only in Manual; the actual
  level is in the `airflow_level` attribute and active unit functions (heat
  recovery, moisture transfer, …) in `active_functions`.
- **Sensors**: temperatures, humidity, CO2, air quality, fan speed and output,
  filter life, preset time remaining, week schedule and alarm log.
- **Alarms**: a Problem binary sensor, one sensor per alarm and a *Clear alarms*
  button.
- **Settings**: eco mode, free cooling, CO2 and humidity setpoints, moisture
  transfer, preset durations and airflows, and more. Installer settings (inputs,
  outputs, sensor corrections, manual overrides) are created disabled; enable
  the ones you need.
- **Firmware**: shows when the IAM has a newer firmware than the one running
  (read-only).

Fahrenheit units are supported; Home Assistant converts to your unit system.

## Tips

- **Poll interval**: *Configure* on the integration (20–600 s, default 60 s).
  Each poll is relayed by the cloud to the unit; stay at 30 s or more, as very
  frequent requests can take the unit offline for a few minutes.
- **Alarm log on a dashboard**:

  ```yaml
  type: markdown
  title: Ventilation alarms
  content: |
    {% for entry in state_attr('sensor.my_unit_alarm_log', 'entries') or [] %}
    - {{ entry }}
    {% endfor %}
  ```

- **Problems**: *Download diagnostics* on the device page gives all register
  values with credentials, serial number and address removed; attach it to an
  issue.

## Translations

To add a language, copy `custom_components/systemair/translations/en.json` to
e.g. `et.json` and translate the values.
