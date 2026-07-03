"""Test Amtrak Tracker integration setup and coordinator."""

from unittest.mock import patch
import aiohttp
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amtrak_tracker import (
    async_setup_entry,
    async_unload_entry,
    AmtrakDataUpdateCoordinator,
)
from custom_components.amtrak_tracker.const import DOMAIN, STATIONS_URL, TRAINS_URL


async def test_setup_unload_entry(hass: HomeAssistant, aioclient_mock) -> None:
    """Test successful setup and unload of a config entry."""
    # Mock API requests
    aioclient_mock.get(STATIONS_URL, json={"NYP": {"name": "New York"}})
    aioclient_mock.get(TRAINS_URL, json={"101": [{"trainNum": "101"}]})

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["monday"],
            "start_time": "08:00",
            "end_time": "17:00",
        },
    )
    config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ) as mock_forward_setups:
        assert await async_setup_entry(hass, config_entry) is True
        await hass.async_block_till_done()

    assert DOMAIN in hass.data
    assert "stations" in hass.data[DOMAIN]
    assert "coordinator" in hass.data[DOMAIN]
    assert len(mock_forward_setups.mock_calls) == 1

    # Unload entry
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ) as mock_unload_platforms:
        assert await async_unload_entry(hass, config_entry) is True
        await hass.async_block_till_done()

    assert len(mock_unload_platforms.mock_calls) == 1
    # Check data is cleaned up
    assert DOMAIN not in hass.data


async def test_setup_entry_stations_fetch_failure(hass: HomeAssistant, aioclient_mock) -> None:
    """Test setup entry when stations list fetch fails (non-200 and exception)."""
    # 1. Non-200 status
    aioclient_mock.get(STATIONS_URL, status=500)
    aioclient_mock.get(TRAINS_URL, json={})

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["monday"],
            "start_time": "08:00",
            "end_time": "17:00",
        },
    )
    config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        assert await async_setup_entry(hass, config_entry) is True
        await hass.async_block_till_done()

    assert hass.data[DOMAIN]["stations"] == {}

    # Unload and retry with exception
    await async_unload_entry(hass, config_entry)
    
    # 2. Client exception
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATIONS_URL, exc=aiohttp.ClientError())
    aioclient_mock.get(TRAINS_URL, json={})

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        assert await async_setup_entry(hass, config_entry) is True
        await hass.async_block_till_done()

    assert hass.data[DOMAIN]["stations"] == {}


async def test_coordinator_update_success(hass: HomeAssistant, aioclient_mock) -> None:
    """Test successful data update in coordinator."""
    coordinator = AmtrakDataUpdateCoordinator(hass)
    mock_data = {"101": [{"trainNum": "101"}]}
    aioclient_mock.get(TRAINS_URL, json=mock_data)

    data = await coordinator._async_update_data()
    assert data == mock_data


async def test_coordinator_update_failures(hass: HomeAssistant, aioclient_mock) -> None:
    """Test coordinator update failure scenarios."""
    coordinator = AmtrakDataUpdateCoordinator(hass)

    # 1. Non-200 status
    aioclient_mock.get(TRAINS_URL, status=500)
    with pytest.raises(UpdateFailed, match="HTTP status 500"):
        await coordinator._async_update_data()

    # 2. Invalid data format (not a dict)
    aioclient_mock.clear_requests()
    aioclient_mock.get(TRAINS_URL, json=["invalid"])
    with pytest.raises(UpdateFailed, match="unexpected data structure"):
        await coordinator._async_update_data()

    # 3. Client connection error
    aioclient_mock.clear_requests()
    aioclient_mock.get(TRAINS_URL, exc=aiohttp.ClientError("connection refused"))
    with pytest.raises(UpdateFailed, match="Network error"):
        await coordinator._async_update_data()

    # 4. General exception
    aioclient_mock.clear_requests()
    aioclient_mock.get(TRAINS_URL, exc=ValueError("unexpected error"))
    with pytest.raises(UpdateFailed, match="Unexpected error"):
        await coordinator._async_update_data()
