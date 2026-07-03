"""The Amtrak Tracker integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    TRAINS_URL,
    STATIONS_URL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amtrak Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Fetch and cache station names/metadata if not already done
    if "stations" not in hass.data[DOMAIN]:
        _LOGGER.debug("Fetching Amtrak stations list")
        session = async_get_clientsession(hass)
        stations = {}
        try:
            async with session.get(STATIONS_URL, timeout=15) as response:
                if response.status == 200:
                    stations = await response.json()
                else:
                    _LOGGER.warning(
                        "Failed to fetch Amtrak stations list: status %s",
                        response.status,
                    )
        except Exception as err:
            _LOGGER.warning("Error fetching Amtrak stations list: %s", err)
        hass.data[DOMAIN]["stations"] = stations

    # Set up the shared coordinator if not already done
    if "coordinator" not in hass.data[DOMAIN]:
        _LOGGER.debug("Initializing Amtrak DataUpdateCoordinator")
        coordinator = AmtrakDataUpdateCoordinator(hass)
        
        # Perform the first refresh to ensure data is populated
        await coordinator.async_config_entry_first_refresh()
        hass.data[DOMAIN]["coordinator"] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # If this was the last entry, we can clean up the coordinator and station cache
    if unload_ok:
        # Check if there are other active entries for this integration
        current_entries = hass.config_entries.async_entries(DOMAIN)
        # Note: the entry currently being unloaded is still in current_entries, 
        # so we check if count is <= 1
        if len(current_entries) <= 1:
            hass.data.pop(DOMAIN, None)

    return unload_ok


class AmtrakDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Amtrak train data from the Amtraker API."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL_SECONDS),
        )
        self.session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Amtraker API."""
        _LOGGER.debug("Polling Amtraker trains API")
        try:
            async with self.session.get(TRAINS_URL, timeout=30) as response:
                if response.status != 200:
                    raise UpdateFailed(
                        f"Error fetching Amtrak trains: HTTP status {response.status}"
                    )
                data = await response.json()
                if not isinstance(data, dict):
                    raise UpdateFailed("API returned unexpected data structure")
                return data
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error updating Amtrak data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating Amtrak data: {err}") from err
