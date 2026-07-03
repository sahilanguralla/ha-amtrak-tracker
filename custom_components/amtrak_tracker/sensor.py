"""Sensor platform for Amtrak Tracker integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ORIGIN,
    CONF_DESTINATION,
    CONF_DAYS,
    CONF_START_TIME,
    CONF_END_TIME,
)
from .__init__ import AmtrakDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Amtrak Tracker sensor from config entry."""
    coordinator: AmtrakDataUpdateCoordinator = hass.data[DOMAIN]["coordinator"]
    stations_cache = hass.data[DOMAIN].get("stations", {})

    async_add_entities(
        [
            AmtrakTrackerSensor(
                coordinator=coordinator,
                entry=entry,
                stations_cache=stations_cache,
            )
        ]
    )


class AmtrakTrackerSensor(CoordinatorEntity[AmtrakDataUpdateCoordinator], SensorEntity):
    """Representation of an Amtrak Tracker sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmtrakDataUpdateCoordinator,
        entry: ConfigEntry,
        stations_cache: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._stations_cache = stations_cache
        
        self._origin = entry.data[CONF_ORIGIN]
        self._destination = entry.data[CONF_DESTINATION]
        self._days = entry.data[CONF_DAYS]
        self._start_time = entry.data[CONF_START_TIME]
        self._end_time = entry.data[CONF_END_TIME]

        # Use station names from cache if available, otherwise default to code
        origin_name = stations_cache.get(self._origin, {}).get("name", self._origin)
        dest_name = stations_cache.get(self._destination, {}).get("name", self._destination)

        self._attr_name = f"{origin_name} to {dest_name} Tracker"
        self._attr_unique_id = f"{DOMAIN}_{self._origin.lower()}_{self._destination.lower()}_{entry.entry_id}"
        
        self._state: datetime | None = None
        self._attributes: dict[str, Any] = {}

        self._update_internal_state()

    def _update_internal_state(self) -> None:
        """Filter trains and update state & attributes from coordinator data."""
        trains_data = self.coordinator.data or {}
        
        matched_trains: list[dict[str, Any]] = []
        upcoming_trains: list[dict[str, Any]] = []

        # Parse config times
        try:
            start_t = datetime.strptime(self._start_time, "%H:%M").time()
            end_t = datetime.strptime(self._end_time, "%H:%M").time()
        except ValueError as err:
            _LOGGER.error("Error parsing configured time range: %s", err)
            return

        # Iterate over all active trains
        for train_num, train_list in trains_data.items():
            if not isinstance(train_list, list):
                continue
                
            for train in train_list:
                stations = train.get("stations", [])
                
                # Find indices of origin and destination stops
                origin_idx = -1
                dest_idx = -1
                for idx, station in enumerate(stations):
                    code = station.get("code", "").upper()
                    if code == self._origin:
                        origin_idx = idx
                    elif code == self._destination:
                        dest_idx = idx

                # The train must visit origin before destination
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

                    # Validate day of the week (using local time of the station)
                    weekday_name = sch_dep.strftime("%A").lower()
                    if weekday_name not in self._days:
                        continue

                    # Validate time range (using local time of the station)
                    dep_time = sch_dep.time()
                    if not (start_t <= dep_time <= end_t):
                        continue

                    # We have a matching train! Gather its info
                    delay_dep = calculate_delay_minutes(origin_stop.get("schDep"), origin_stop.get("dep"))
                    delay_arr = calculate_delay_minutes(dest_stop.get("schArr"), dest_stop.get("arr"))

                    train_info = {
                        "train_number": train.get("trainNum"),
                        "route_name": train.get("routeName"),
                        "train_id": train.get("trainID"),
                        "train_state": train.get("trainState"),
                        "scheduled_departure": origin_stop.get("schDep"),
                        "estimated_departure": origin_stop.get("dep") or origin_stop.get("schDep"),
                        "departure_status": origin_stop.get("status"),
                        "scheduled_arrival": dest_stop.get("schArr"),
                        "estimated_arrival": dest_stop.get("arr") or dest_stop.get("schArr"),
                        "arrival_status": dest_stop.get("status"),
                        "delay_departure_minutes": delay_dep,
                        "delay_arrival_minutes": delay_arr,
                        "latitude": train.get("lat"),
                        "longitude": train.get("lon"),
                        "speed_mph": train.get("velocity"),
                    }
                    
                    matched_trains.append(train_info)

                    # Only count as upcoming if it has not departed from origin yet
                    if origin_stop.get("status") != "Departed":
                        upcoming_trains.append(train_info)

        # Sort lists by scheduled departure time
        def get_sch_dep(t):
            try:
                return datetime.fromisoformat(t["scheduled_departure"])
            except ValueError:
                return datetime.min

        matched_trains.sort(key=get_sch_dep)
        upcoming_trains.sort(key=get_sch_dep)

        # Build sensor attributes
        origin_name = self._stations_cache.get(self._origin, {}).get("name", self._origin)
        dest_name = self._stations_cache.get(self._destination, {}).get("name", self._destination)

        attrs: dict[str, Any] = {
            "origin_code": self._origin,
            "origin_name": origin_name,
            "destination_code": self._destination,
            "destination_name": dest_name,
            "matched_trains_count": len(matched_trains),
            "upcoming_trains_count": len(upcoming_trains),
            "matched_trains": matched_trains,
            "upcoming_trains": upcoming_trains,
        }

        # Find the first train that hasn't finished its run to actively track
        active_train = None
        for train in matched_trains:
            if train["arrival_status"] != "Departed" and train["train_state"] != "Completed":
                active_train = train
                break

        # If there's an active train, set state and train-specific attributes
        if active_train:
            # The state of a TIMESTAMP sensor must be a datetime object
            try:
                self._state = datetime.fromisoformat(active_train["estimated_departure"])
            except ValueError:
                self._state = None
                
            attrs.update({
                "train_number": active_train["train_number"],
                "route_name": active_train["route_name"],
                "train_id": active_train["train_id"],
                "train_state": active_train["train_state"],
                "scheduled_departure": active_train["scheduled_departure"],
                "estimated_departure": active_train["estimated_departure"],
                "departure_status": active_train["departure_status"],
                "scheduled_arrival": active_train["scheduled_arrival"],
                "estimated_arrival": active_train["estimated_arrival"],
                "arrival_status": active_train["arrival_status"],
                "delay_departure_minutes": active_train["delay_departure_minutes"],
                "delay_arrival_minutes": active_train["delay_arrival_minutes"],
                "train_latitude": active_train["latitude"],
                "train_longitude": active_train["longitude"],
                "train_speed_mph": active_train["speed_mph"],
            })
        else:
            self._state = None
            attrs.update({
                "train_number": None,
                "route_name": None,
                "train_id": None,
                "train_state": None,
                "scheduled_departure": None,
                "estimated_departure": None,
                "departure_status": None,
                "scheduled_arrival": None,
                "estimated_arrival": None,
                "arrival_status": None,
                "delay_departure_minutes": None,
                "delay_arrival_minutes": None,
                "train_latitude": None,
                "train_longitude": None,
                "train_speed_mph": None,
            })

        self._attributes = attrs

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self._attributes

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_internal_state()
        super()._handle_coordinator_update()
