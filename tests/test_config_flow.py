"""Test Amtrak Tracker config flow."""

from unittest.mock import patch
import aiohttp
import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.amtrak_tracker.const import (
    DOMAIN,
    CONF_ORIGIN,
    CONF_DESTINATION,
    CONF_DAYS,
    CONF_START_TIME,
    CONF_END_TIME,
    STATIONS_URL,
)

MOCK_STATIONS = {
    "NYP": {"name": "New York Penn Station"},
    "PHL": {"name": "Philadelphia 30th Street"},
    "WAS": {"name": "Washington Union Station"},
}


async def test_show_form(hass: HomeAssistant, aioclient_mock) -> None:
    """Test that the user step form is shown."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_flow_success(hass: HomeAssistant, aioclient_mock) -> None:
    """Test successful configuration flow."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.amtrak_tracker.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_ORIGIN: "NYP",
                CONF_DESTINATION: "PHL",
                CONF_DAYS: ["monday", "friday"],
                CONF_START_TIME: "08:00",
                CONF_END_TIME: "17:00",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "NYP to PHL Tracker"
    assert result["data"] == {
        CONF_ORIGIN: "NYP",
        CONF_DESTINATION: "PHL",
        CONF_DAYS: ["monday", "friday"],
        CONF_START_TIME: "08:00",
        CONF_END_TIME: "17:00",
        "notify_enabled": False,
        "notify_service": "persistent_notification",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_flow_same_stations(hass: HomeAssistant, aioclient_mock) -> None:
    """Test error when origin and destination are the same."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "NYP",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "08:00",
            CONF_END_TIME: "17:00",
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "same_stations"}


async def test_flow_invalid_time_format(hass: HomeAssistant, aioclient_mock) -> None:
    """Test error when time format is invalid."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)

    # Invalid start time
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "PHL",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "invalid",
            CONF_END_TIME: "17:00",
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_START_TIME: "invalid_time_format"}

    # Invalid end time
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "PHL",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "08:00",
            CONF_END_TIME: "invalid",
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_END_TIME: "invalid_time_format"}


async def test_flow_invalid_time_range(hass: HomeAssistant, aioclient_mock) -> None:
    """Test error when start time is after end time."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "PHL",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "17:00",
            CONF_END_TIME: "08:00",
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_time_range"}


async def test_flow_invalid_stations(hass: HomeAssistant, aioclient_mock) -> None:
    """Test error when stations are invalid."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)

    # Invalid origin
    with patch(
        "custom_components.amtrak_tracker.config_flow.AmtrakTrackerConfigFlow._async_get_stations",
        return_value={},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "XXX",
            CONF_DESTINATION: "PHL",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "08:00",
            CONF_END_TIME: "17:00",
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_ORIGIN: "invalid_origin"}

    # Invalid destination
    with patch(
        "custom_components.amtrak_tracker.config_flow.AmtrakTrackerConfigFlow._async_get_stations",
        return_value={},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "YYY",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "08:00",
            CONF_END_TIME: "17:00",
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_DESTINATION: "invalid_destination"}



async def test_flow_stations_api_offline(hass: HomeAssistant, aioclient_mock) -> None:
    """Test config flow when stations API returns non-200 or fails."""
    # API returns non-200
    aioclient_mock.get(STATIONS_URL, status=500)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "PHL",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "08:00",
            CONF_END_TIME: "17:00",
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_stations_api_network_error(hass: HomeAssistant, aioclient_mock) -> None:
    """Test config flow when stations API has network error."""
    aioclient_mock.get(STATIONS_URL, exc=aiohttp.ClientError())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_ORIGIN: "NYP",
            CONF_DESTINATION: "PHL",
            CONF_DAYS: ["monday"],
            CONF_START_TIME: "08:00",
            CONF_END_TIME: "17:00",
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
