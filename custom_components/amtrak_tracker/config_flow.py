"""Config flow for Amtrak Tracker integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DAYS,
    CONF_DESTINATION,
    CONF_END_TIME,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_LIVE_ACTIVITY,
    CONF_ORIGIN,
    CONF_START_TIME,
    DOMAIN,
    STATIONS_URL,
)
from .notify_targets import get_notify_target_options

_LOGGER = logging.getLogger(__name__)


async def validate_input(
    hass: HomeAssistant, data: dict[str, Any], stations: dict[str, Any] | None = None
) -> dict[str, str]:
    """Validate the user input.

    Returns a dictionary of errors, which will be empty if validation is successful.
    """
    errors: dict[str, str] = {}

    origin = data[CONF_ORIGIN].strip().upper()
    destination = data[CONF_DESTINATION].strip().upper()

    if origin == destination:
        errors["base"] = "same_stations"
        return errors

    # Validate times
    try:
        start_t = datetime.strptime(data[CONF_START_TIME], "%H:%M").time()
    except ValueError:
        errors[CONF_START_TIME] = "invalid_time_format"
        return errors

    try:
        end_t = datetime.strptime(data[CONF_END_TIME], "%H:%M").time()
    except ValueError:
        errors[CONF_END_TIME] = "invalid_time_format"
        return errors

    if start_t >= end_t:
        errors["base"] = "invalid_time_range"
        return errors

    # Validate stations
    if not stations:
        session = async_get_clientsession(hass)
        try:
            async with session.get(STATIONS_URL, timeout=10) as response:
                if response.status != 200:
                    errors["base"] = "cannot_connect"
                    return errors
                stations = await response.json()
        except (aiohttp.ClientError, Exception) as err:
            _LOGGER.error("Error connecting to Amtraker API: %s", err)
            errors["base"] = "cannot_connect"
            return errors

    if origin not in stations:
        errors[CONF_ORIGIN] = "invalid_origin"
    if destination not in stations:
        errors[CONF_DESTINATION] = "invalid_destination"

    return errors


class AmtrakTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amtrak Tracker."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        super().__init__()
        self._stations: dict[str, Any] | None = None

    async def _async_get_stations(self) -> dict[str, Any]:
        """Fetch and cache station list."""
        if self._stations is not None:
            return self._stations

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(STATIONS_URL, timeout=10) as response:
                if response.status == 200:
                    self._stations = await response.json()
                    return self._stations
        except Exception as err:
            _LOGGER.warning("Could not fetch stations list for configuration: %s", err)
        return {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AmtrakTrackerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return AmtrakTrackerOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        stations = await self._async_get_stations()

        if user_input is not None:
            errors = await validate_input(self.hass, user_input, stations)
            if not errors:
                # Normalize inputs
                origin = user_input[CONF_ORIGIN].strip().upper()
                destination = user_input[CONF_DESTINATION].strip().upper()
                
                title = f"{origin} to {destination} Tracker"
                
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_ORIGIN: origin,
                        CONF_DESTINATION: destination,
                        CONF_DAYS: user_input[CONF_DAYS],
                        CONF_START_TIME: user_input[CONF_START_TIME],
                        CONF_END_TIME: user_input[CONF_END_TIME],
                        CONF_NOTIFY_ENABLED: user_input.get(CONF_NOTIFY_ENABLED, False),
                        CONF_NOTIFY_SERVICE: user_input.get(CONF_NOTIFY_SERVICE, "persistent_notification"),
                        CONF_NOTIFY_LIVE_ACTIVITY: user_input.get(CONF_NOTIFY_LIVE_ACTIVITY, True),
                    },
                )

        # Prepare schema dynamically with searchable dropdowns
        if stations:
            station_options = [
                {"value": code, "label": f"{info.get('name', code)} ({code})"}
                for code, info in stations.items()
            ]
            station_options.sort(key=lambda x: x["label"])
            
            origin_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=station_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            dest_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=station_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            # Fallback to simple text inputs if Amtraker API is offline/unavailable
            origin_selector = selector.TextSelector()
            dest_selector = selector.TextSelector()

        notify_options = get_notify_target_options(self.hass)

        schema = vol.Schema(
            {
                vol.Required(CONF_ORIGIN): origin_selector,
                vol.Required(CONF_DESTINATION): dest_selector,
                vol.Required(
                    CONF_DAYS,
                    default=[
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                    ],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "monday", "label": "Monday"},
                            {"value": "tuesday", "label": "Tuesday"},
                            {"value": "wednesday", "label": "Wednesday"},
                            {"value": "thursday", "label": "Thursday"},
                            {"value": "friday", "label": "Friday"},
                            {"value": "saturday", "label": "Saturday"},
                            {"value": "sunday", "label": "Sunday"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                        multiple=True,
                    )
                ),
                vol.Required(CONF_START_TIME, default="08:00"): str,
                vol.Required(CONF_END_TIME, default="17:00"): str,
                vol.Optional(CONF_NOTIFY_ENABLED, default=False): bool,
                vol.Optional(
                    CONF_NOTIFY_SERVICE, default="persistent_notification"
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notify_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_NOTIFY_LIVE_ACTIVITY, default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )


class AmtrakTrackerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Amtrak Tracker."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry."""
        return self._config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values to set as defaults
        notify_enabled = self.config_entry.options.get(
            CONF_NOTIFY_ENABLED,
            self.config_entry.data.get(CONF_NOTIFY_ENABLED, False)
        )
        notify_service = self.config_entry.options.get(
            CONF_NOTIFY_SERVICE,
            self.config_entry.data.get(CONF_NOTIFY_SERVICE, "persistent_notification")
        )
        notify_live_activity = self.config_entry.options.get(
            CONF_NOTIFY_LIVE_ACTIVITY,
            self.config_entry.data.get(CONF_NOTIFY_LIVE_ACTIVITY, True)
        )
        days = self.config_entry.options.get(
            CONF_DAYS,
            self.config_entry.data.get(CONF_DAYS, ["monday", "tuesday", "wednesday", "thursday", "friday"])
        )
        start_time = self.config_entry.options.get(
            CONF_START_TIME,
            self.config_entry.data.get(CONF_START_TIME, "08:00")
        )
        end_time = self.config_entry.options.get(
            CONF_END_TIME,
            self.config_entry.data.get(CONF_END_TIME, "17:00")
        )

        notify_options = get_notify_target_options(self.hass)

        schema = vol.Schema(
            {
                vol.Required(CONF_DAYS, default=days): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "monday", "label": "Monday"},
                            {"value": "tuesday", "label": "Tuesday"},
                            {"value": "wednesday", "label": "Wednesday"},
                            {"value": "thursday", "label": "Thursday"},
                            {"value": "friday", "label": "Friday"},
                            {"value": "saturday", "label": "Saturday"},
                            {"value": "sunday", "label": "Sunday"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                        multiple=True,
                    )
                ),
                vol.Required(CONF_START_TIME, default=start_time): str,
                vol.Required(CONF_END_TIME, default=end_time): str,
                vol.Optional(CONF_NOTIFY_ENABLED, default=notify_enabled): bool,
                vol.Optional(
                    CONF_NOTIFY_SERVICE, default=notify_service
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notify_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_NOTIFY_LIVE_ACTIVITY, default=notify_live_activity): bool,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema
        )

