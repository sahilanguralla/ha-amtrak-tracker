"""Sensor platform for Amtrak Tracker integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
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
from .notifications import calculate_delay_minutes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Amtrak Tracker sensors from config entry."""
    coordinator: AmtrakDataUpdateCoordinator = hass.data[DOMAIN]["coordinator"]
    stations_cache = hass.data[DOMAIN].get("stations", {})

    sensors = []
    for index in range(3):
        sensors.append(
            AmtrakTrainSensor(
                coordinator=coordinator,
                entry=entry,
                stations_cache=stations_cache,
                index=index,
                sensor_type="departure",
            )
        )
        sensors.append(
            AmtrakTrainSensor(
                coordinator=coordinator,
                entry=entry,
                stations_cache=stations_cache,
                index=index,
                sensor_type="schedule",
            )
        )

    async_add_entities(sensors)


class AmtrakTrainSensor(CoordinatorEntity[AmtrakDataUpdateCoordinator], SensorEntity):
    """Representation of an Amtrak Train sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmtrakDataUpdateCoordinator,
        entry: ConfigEntry,
        stations_cache: dict[str, Any],
        index: int,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._stations_cache = stations_cache
        self._index = index
        self._sensor_type = sensor_type

        self._origin = entry.options.get(CONF_ORIGIN, entry.data.get(CONF_ORIGIN))
        self._destination = entry.options.get(CONF_DESTINATION, entry.data.get(CONF_DESTINATION))
        self._days = entry.options.get(CONF_DAYS, entry.data.get(CONF_DAYS))
        self._start_time = entry.options.get(CONF_START_TIME, entry.data.get(CONF_START_TIME))
        self._end_time = entry.options.get(CONF_END_TIME, entry.data.get(CONF_END_TIME))

        # Use station names from cache if available, otherwise default to code
        self._origin_name = stations_cache.get(self._origin, {}).get("name", self._origin)
        self._dest_name = stations_cache.get(self._destination, {}).get("name", self._destination)

        ordinal = {0: "1st", 1: "2nd", 2: "3rd"}[index]
        if sensor_type == "departure":
            self._attr_name = f"#{index + 1} Train Time"
            self._attr_unique_id = f"{DOMAIN}_{self._origin.lower()}_{self._destination.lower()}_{entry.entry_id}_{ordinal.lower()}_upcoming_train"
            self._attr_icon = "mdi:train"
        else:
            self._attr_name = f"#{index + 1} Train Delay"
            self._attr_unique_id = f"{DOMAIN}_{self._origin.lower()}_{self._destination.lower()}_{entry.entry_id}_{ordinal.lower()}_train_current_schedule"
            self._attr_native_unit_of_measurement = "min"
            self._attr_icon = "mdi:timer-alert-outline"

        self._state: Any = None
        self._attributes: dict[str, Any] = {}

        self._update_internal_state()

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self._origin.lower()}_{self._destination.lower()}_{self._entry.entry_id}")},
            "name": f"{self._origin_name} to {self._dest_name} Amtrak Tracker",
            "manufacturer": "Amtrak",
            "entry_type": "service",
        }

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

        # Sort lists by estimated departure time
        def get_est_dep(t):
            try:
                return datetime.fromisoformat(t["estimated_departure"])
            except (ValueError, TypeError):
                return datetime.min

        matched_trains.sort(key=get_est_dep)
        upcoming_trains.sort(key=get_est_dep)

        # Build sensor attributes
        attrs: dict[str, Any] = {
            "origin_code": self._origin,
            "origin_name": self._origin_name,
            "destination_code": self._destination,
            "destination_name": self._dest_name,
            "matched_trains_count": len(matched_trains),
            "upcoming_trains_count": len(upcoming_trains),
        }

        train_info = None
        if self._index < len(upcoming_trains):
            train_info = upcoming_trains[self._index]

        if train_info:
            if self._sensor_type == "departure":
                try:
                    dt = datetime.fromisoformat(train_info["estimated_departure"])
                    self._state = dt.strftime("%I:%M %p").lstrip('0')
                except (ValueError, TypeError):
                    self._state = None
            else:
                self._state = train_info["delay_departure_minutes"]

            attrs.update({
                "train_number": train_info["train_number"],
                "route_name": train_info["route_name"],
                "train_id": train_info["train_id"],
                "train_state": train_info["train_state"],
                "scheduled_departure": train_info["scheduled_departure"],
                "estimated_departure": train_info["estimated_departure"],
                "departure_status": train_info["departure_status"],
                "scheduled_arrival": train_info["scheduled_arrival"],
                "estimated_arrival": train_info["estimated_arrival"],
                "arrival_status": train_info["arrival_status"],
                "delay_departure_minutes": train_info["delay_departure_minutes"],
                "delay_arrival_minutes": train_info["delay_arrival_minutes"],
                "train_latitude": train_info["latitude"],
                "train_longitude": train_info["longitude"],
                "train_speed_mph": train_info["speed_mph"],
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
    def name(self) -> str | None:
        """Return the name of the sensor."""
        if not self.entity_id:
            return self._attr_name

        train_number = self._attributes.get("train_number")
        if not train_number:
            return self._attr_name

        if self._sensor_type == "departure":
            return f"#{self._index + 1} Train {train_number} Time"
        return f"#{self._index + 1} Train {train_number} Delay"

    @property
    def native_value(self) -> Any:
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
