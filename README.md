# Amtrak Tracker for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration that tracks Amtrak trains between an origin station and a destination station on specific days and time ranges using the unofficial community-maintained [Amtraker API](https://amtraker.com).

## Features
- **Searchable Station Dropdowns:** Select origin and destination stations easily from the configuration UI.
- **Dynamic Scheduling:** Filter tracks by specific days of the week (e.g. only Monday and Wednesday) and a scheduled departure window (e.g. 08:00 to 12:00).
- **Timezone Awareness:** Calculates weekdays and time offsets relative to the origin station's local timezone.
- **Estimated and Scheduled Delays:** Computes real-time delays at both departure (origin) and arrival (destination) stations in minutes.
- **Entity Attributes:** Exposes detailed train attributes including name, number, current coordinates, speed, status, and a full list of all matching runs for the day.
- **Optimized Network Fetching:** Shares a single consolidated endpoint poll (`https://api.amtraker.com/v3/trains`) across all configured sensors via a `DataUpdateCoordinator` to respect API rate limits.

---

## Installation

### Via HACS (Recommended)
1. Open **HACS** in your Home Assistant UI.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Paste the URL of this repository: `https://github.com/sahilanguralla/ha-amtrak-tracker`.
4. Select **Integration** as the Category and click **Add**.
5. Find **Amtrak Tracker** in the HACS list and click **Download**.
6. Restart Home Assistant.

### Manual Installation
1. Download the latest release from the GitHub Releases page.
2. Extract the contents and copy the `custom_components/amtrak_tracker` folder into your Home Assistant config's `custom_components/` directory.
3. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings -> Devices & Services**.
2. Click **+ Add Integration** in the bottom right.
3. Search for **Amtrak Tracker** and select it.
4. Fill in the configuration details:
   - **Origin Station:** Choose your starting station (e.g. *New York Penn (NYP)*) from the searchable list.
   - **Destination Station:** Choose your destination station (e.g. *Philadelphia 30th Street (PHL)*) from the list.
   - **Days of the week:** Check the days you want to track.
   - **Start time:** The start of the scheduled departure time range (HH:MM, local time at origin).
   - **End time:** The end of the scheduled departure time range (HH:MM, local time at origin).
5. Click **Submit**.

---

## Sensor State & Attributes

Each configured tracker creates a sensor entity (e.g. `sensor.nyp_to_phl_tracker`).

### State
The main state of the departure sensor is the **estimated departure time** of the next upcoming train in the configured window (formatted as a local 12-hour time string, e.g. `4:32 PM`). If no trains match or all matching trains have already departed, the state will show as `Unknown` / `None`.

### Attributes
The sensor exposes the following attributes for the next upcoming train:

| Attribute | Description |
| :--- | :--- |
| `origin_code` | Origin station code (e.g., `NYP`). |
| `origin_name` | Full name of origin station. |
| `destination_code` | Destination station code (e.g., `PHL`). |
| `destination_name` | Full name of destination station. |
| `train_number` | Active train number (e.g. `19`). |
| `route_name` | Route/Train name (e.g., `Crescent`). |
| `train_state` | State of the train (e.g., `Active`, `Predeparture`, `Completed`). |
| `departure_status` | Status at origin (e.g., `Enroute`, `Station`, `Departed`). |
| `scheduled_departure` | Scheduled departure timestamp. |
| `estimated_departure` | Estimated/actual departure timestamp. |
| `delay_departure_minutes` | Departure delay in minutes (positive values represent delays). |
| `scheduled_arrival` | Scheduled arrival timestamp. |
| `estimated_arrival` | Estimated/actual arrival timestamp. |
| `delay_arrival_minutes` | Arrival delay at destination in minutes. |
| `train_latitude` | Latitude coordinate of the train's current position. |
| `train_longitude` | Longitude coordinate of the train's current position. |
| `train_speed_mph` | Current speed of the train in miles per hour. |
| `matched_trains_count` | Total matching runs scheduled for the configured day. |
| `upcoming_trains_count` | Count of matching runs that have not yet departed. |
| `matched_trains` | A list of all matching trains for the day (both departed and upcoming) for template iteration. |
| `upcoming_trains` | A list of all upcoming trains for the duration that have not yet departed. |

---

## Example Automation

This automation sends a notification to your mobile app if your tracked train departs from the origin station with a delay of more than 10 minutes.

```yaml
alias: "Notify on Amtrak Train Delay"
trigger:
  - platform: numeric_state
    entity_id: sensor.nyp_to_phl_tracker
    attribute: delay_departure_minutes
    above: 10
condition:
  # Ensure there is an active train selected
  - condition: template
    value_template: "{{ state_attr('sensor.nyp_to_phl_tracker', 'train_number') != None }}"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Amtrak Train Delayed"
      message: >
        Amtrak {{ state_attr('sensor.nyp_to_phl_tracker', 'route_name') }} (Train {{ state_attr('sensor.nyp_to_phl_tracker', 'train_number') }}) is departing {{ state_attr('sensor.nyp_to_phl_tracker', 'origin_name') }} delayed by {{ state_attr('sensor.nyp_to_phl_tracker', 'delay_departure_minutes') }} minutes. Estimated departure: {{ state_attr('sensor.nyp_to_phl_tracker', 'estimated_departure') }}.
```

---

## API Attribution & Disclaimer
This project is an unofficial integration and is not endorsed by or affiliated with Amtrak. Data is retrieved using the [Amtraker API](https://amtraker.com) v3 developed by Piero Maddaleni. Please use responsibly and respect rate limits.
