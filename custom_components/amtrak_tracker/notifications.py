"""Notification manager for Amtrak Tracker integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DAYS,
    CONF_DESTINATION,
    CONF_END_TIME,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_ORIGIN,
    CONF_START_TIME,
    DOMAIN,
)
from .notify_targets import PERSISTENT_NOTIFICATION, async_clear_notify, async_send_notify, is_mobile_app_push_target


def calculate_delay_minutes(scheduled_str: str | None, estimated_str: str | None) -> int | None:
    """Calculate the delay in minutes between scheduled and estimated/actual times."""
    if not scheduled_str or not estimated_str:
        return None
    try:
        sch = datetime.fromisoformat(scheduled_str)
        est = datetime.fromisoformat(estimated_str)
        diff = est - sch
        return int(diff.total_seconds() / 60)
    except Exception as err:
        _LOGGER.debug("Error calculating delay from %s and %s: %s", scheduled_str, estimated_str, err)
        return None


_LOGGER = logging.getLogger(__name__)


def get_upcoming_trains_for_today(
    hass: HomeAssistant,
    entry: ConfigEntry,
    trains_data: dict[str, Any],
    stations_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    """Get sorted list of upcoming trains scheduled for today."""
    origin = entry.options.get(CONF_ORIGIN, entry.data.get(CONF_ORIGIN))
    destination = entry.options.get(CONF_DESTINATION, entry.data.get(CONF_DESTINATION))
    start_time_str = entry.options.get(CONF_START_TIME, entry.data.get(CONF_START_TIME, "08:00"))
    end_time_str = entry.options.get(CONF_END_TIME, entry.data.get(CONF_END_TIME, "17:00"))

    # Parse config times
    try:
        start_t = datetime.strptime(start_time_str, "%H:%M").time()
        end_t = datetime.strptime(end_time_str, "%H:%M").time()
    except ValueError as err:
        _LOGGER.error("Error parsing configured time range: %s", err)
        return []

    now = dt_util.now()
    today_date = now.date()

    upcoming_trains: list[dict[str, Any]] = []

    for train_num, train_list in trains_data.items():
        if not isinstance(train_list, list):
            continue

        for train in train_list:
            stations = train.get("stations", [])
            
            origin_idx = -1
            dest_idx = -1
            for idx, station in enumerate(stations):
                code = station.get("code", "").upper()
                if code == origin:
                    origin_idx = idx
                elif code == destination:
                    dest_idx = idx

            # Train must visit origin before destination
            if origin_idx != -1 and dest_idx != -1 and origin_idx < dest_idx:
                origin_stop = stations[origin_idx]
                dest_stop = stations[dest_idx]

                sch_dep_str = origin_stop.get("schDep")
                if not sch_dep_str:
                    continue

                try:
                    sch_dep = datetime.fromisoformat(sch_dep_str)
                except ValueError:
                    continue

                # Ensure the train's scheduled departure is today in the station's local time
                now_station = now.astimezone(sch_dep.tzinfo)
                if sch_dep.date() != now_station.date():
                    continue

                # Scheduled departure time must be within configured time window (using station local time)
                dep_time = sch_dep.time()
                if not (start_t <= dep_time <= end_t):
                    continue

                # Train is upcoming only if it has not departed yet
                if origin_stop.get("status") == "Departed":
                    continue

                delay_dep = calculate_delay_minutes(origin_stop.get("schDep"), origin_stop.get("dep"))

                train_info = {
                    "train_number": train.get("trainNum"),
                    "route_name": train.get("routeName"),
                    "train_id": train.get("trainID"),
                    "estimated_departure": origin_stop.get("dep") or origin_stop.get("schDep"),
                    "delay_departure_minutes": delay_dep,
                }
                upcoming_trains.append(train_info)

    # Sort trains by estimated departure time
    def get_est_dep(t):
        try:
            return datetime.fromisoformat(t["estimated_departure"])
        except (ValueError, TypeError):
            return datetime.min

    upcoming_trains.sort(key=get_est_dep)
    return upcoming_trains


async def async_update_train_notifications(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Update upcoming train notifications for a config entry."""
    if DOMAIN not in hass.data:
        return
    # Check if notification is enabled
    notify_enabled = entry.options.get(CONF_NOTIFY_ENABLED, entry.data.get(CONF_NOTIFY_ENABLED, False))
    if not notify_enabled:
        _LOGGER.debug("Notifications are disabled for entry %s", entry.entry_id)
        await async_dismiss_notifications(hass, entry)
        return

    # Check if today is a configured day
    days = entry.options.get(CONF_DAYS, entry.data.get(CONF_DAYS, []))
    now = dt_util.now()
    current_weekday = now.strftime("%A").lower()

    if current_weekday not in days:
        _LOGGER.debug("Today (%s) is not a configured day for entry %s", current_weekday, entry.entry_id)
        await async_dismiss_notifications(hass, entry)
        return

    # Fetch coordinator data
    trains_data = coordinator.data or {}
    stations_cache = hass.data[DOMAIN].get("stations", {})

    upcoming_trains = get_upcoming_trains_for_today(hass, entry, trains_data, stations_cache)

    if not upcoming_trains:
        _LOGGER.debug("No upcoming trains remaining for today for entry %s", entry.entry_id)
        await async_dismiss_notifications(hass, entry)
        return

    # Get the first upcoming train
    train = upcoming_trains[0]
    train_number = train["train_number"]
    route_name = train["route_name"] or "Amtrak"
    est_dep_str = train["estimated_departure"]
    delay = train["delay_departure_minutes"]

    # Parse and format the estimated departure time
    formatted_time = ""
    try:
        dt = datetime.fromisoformat(est_dep_str)
        formatted_time = dt.strftime("%I:%M %p").lstrip('0')
    except (ValueError, TypeError):
        formatted_time = est_dep_str

    # Format delay string
    if delay is None or delay == 0:
        delay_string = "On time"
    elif delay > 0:
        delay_string = f"{delay} min delay"
    else:
        delay_string = f"{abs(delay)} min early"

    # Get station names
    origin = entry.options.get(CONF_ORIGIN, entry.data.get(CONF_ORIGIN))
    destination = entry.options.get(CONF_DESTINATION, entry.data.get(CONF_DESTINATION))
    origin_name = stations_cache.get(origin, {}).get("name", origin)
    dest_name = stations_cache.get(destination, {}).get("name", destination)

    # Construct Title & Message & Subtitle
    title = f"Upcoming Train {train_number} ({delay_string})"
    message = f"Departing {origin_name} at {formatted_time} for {dest_name}."
    subtitle = f"Train {train_number}: {delay_string}"

    notify_service = entry.options.get(CONF_NOTIFY_SERVICE, entry.data.get(CONF_NOTIFY_SERVICE, PERSISTENT_NOTIFICATION))

    # De-duplicate notifications
    entry_state = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    last_notification = entry_state.get("last_notification")

    new_notification_state = {
        "service": notify_service,
        "title": title,
        "message": message,
        "subtitle": subtitle,
    }

    # Check if the notification still exists in Home Assistant if using persistent_notification
    notification_exists = True
    if notify_service == PERSISTENT_NOTIFICATION:
        active_notifications = hass.data.get("persistent_notification", {})
        notification_id = f"amtrak_tracker_{entry.entry_id}"
        notification_exists = notification_id in active_notifications

    if last_notification == new_notification_state and notification_exists:
        _LOGGER.debug("Notification content unchanged and still active; skipping update")
        return

    _LOGGER.info(
        "Sending upcoming train notification via %s: %s - %s",
        notify_service,
        title,
        message,
    )

    try:
        if notify_service == PERSISTENT_NOTIFICATION:
            await async_send_notify(
                hass,
                notify_service,
                title=title,
                message=message,
                data={"notification_id": f"amtrak_tracker_{entry.entry_id}"},
            )
        else:
            # Calculate Unix timestamp of estimated departure for the chronometer
            when_timestamp = None
            if est_dep_str:
                try:
                    dt = datetime.fromisoformat(est_dep_str)
                    when_timestamp = int(dt.timestamp())
                except (ValueError, TypeError):
                    pass

            data_payload = {
                "tag": f"amtrak_tracker_{entry.entry_id}",
            }

            if is_mobile_app_push_target(hass, notify_service):
                # Tailor message for Live Activity: static time is replaced by ticking chronometer,
                # so we display origin/destination and current delay status in the message.
                live_activity_message = f"Departing {origin_name} for {dest_name} ({delay_string})"
                data_payload.update({
                    "subtitle": delay_string,
                    "persistent": True,
                    "sticky": True,
                    "live_update": True,
                })
                if when_timestamp is not None:
                    data_payload.update({
                        "chronometer": True,
                        "when": when_timestamp,
                    })

                await async_send_notify(
                    hass,
                    notify_service,
                    title=f"Upcoming Amtrak Train {train_number}",
                    message=live_activity_message,
                    data=data_payload,
                )
            else:
                data_payload.update({
                    "subtitle": delay_string,
                    "persistent": True,
                    "sticky": True,
                })
                await async_send_notify(
                    hass,
                    notify_service,
                    title=f"Upcoming Amtrak Train {train_number}",
                    message=message,
                    data=data_payload,
                )
        entry_state["last_notification"] = new_notification_state
    except Exception as err:
        _LOGGER.error("Failed to send train notification: %s", err)


async def async_dismiss_notifications(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear/dismiss any active notifications for this entry."""
    if DOMAIN not in hass.data:
        return
    entry_state = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    last_notification = entry_state.get("last_notification")

    if last_notification is None:
        return

    notify_service = last_notification["service"]
    _LOGGER.info("Dismissing train notification via %s", notify_service)

    try:
        if notify_service == PERSISTENT_NOTIFICATION:
            await async_clear_notify(
                hass,
                notify_service,
                tag=f"amtrak_tracker_{entry.entry_id}",
                notification_id=f"amtrak_tracker_{entry.entry_id}",
            )
        else:
            await async_clear_notify(
                hass,
                notify_service,
                tag=f"amtrak_tracker_{entry.entry_id}",
            )
    except Exception as err:
        _LOGGER.error("Failed to clear train notification: %s", err)

    entry_state["last_notification"] = None
