"""Test upcoming train notifications for Amtrak Tracker."""

from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
import homeassistant.util.dt as dt_util

from custom_components.amtrak_tracker.const import (
    DOMAIN,
    STATIONS_URL,
    TRAINS_URL,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
)
from custom_components.amtrak_tracker.notifications import (
    async_update_train_notifications,
    async_dismiss_notifications,
)

MOCK_STATIONS = {
    "NYP": {"name": "New York Penn Station"},
    "PHL": {"name": "Philadelphia 30th Street"},
}

# Friday, July 3rd, 2026
MOCK_NOW = datetime(2026, 7, 3, 10, 0, 0, tzinfo=dt_util.get_time_zone("America/New_York"))

MOCK_TRAINS = {
    "101": [
        {
            "trainNum": "101",
            "routeName": "Keystone",
            "trainID": "101-1",
            "trainState": "Active",
            "lat": 40.0,
            "lon": -74.0,
            "velocity": 80.0,
            "stations": [
                {
                    "code": "NYP",
                    "schDep": "2026-07-03T09:00:00-04:00",
                    "dep": "2026-07-03T09:15:00-04:00", # 15 min delay
                    "status": "Enroute",
                },
                {
                    "code": "PHL",
                    "schArr": "2026-07-03T10:30:00-04:00",
                    "arr": "2026-07-03T10:45:00-04:00",
                    "status": "Enroute",
                }
            ]
        }
    ]
}


async def test_notification_creation_and_deduplication(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is created, updated on changes, and skipped on duplicate data."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "persistent_notification",
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW), \
         patch.object(hass.services, "async_call", autospec=True) as mock_call:
        
        # Setup entry
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        print("ACTUAL MOCK CALLS:", mock_call.mock_calls)

        mock_call.assert_any_call(
            "persistent_notification",
            "create",
            {
                "title": "Upcoming Train 101 (15 min delay)",
                "message": "Departing New York Penn Station at 9:15 AM for Philadelphia 30th Street.",
                "notification_id": f"amtrak_tracker_{config_entry.entry_id}",
            }
        )
        
        # Reset mock
        mock_call.reset_mock()

        # Update coordinator (data unchanged)
        coordinator = hass.data[DOMAIN]["coordinator"]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # No new notification should be sent (de-duplication)
        assert not any(call[0][0] == "persistent_notification" and call[0][1] == "create" for call in mock_call.mock_calls)

        # Update coordinator with new delay (30 mins delay)
        import copy
        updated_trains = copy.deepcopy(MOCK_TRAINS)
        updated_trains["101"][0]["stations"][0]["dep"] = "2026-07-03T09:30:00-04:00"
        aioclient_mock.clear_requests()
        aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
        aioclient_mock.get(TRAINS_URL, json=updated_trains)

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_call.assert_any_call(
            "persistent_notification",
            "create",
            {
                "title": "Upcoming Train 101 (30 min delay)",
                "message": "Departing New York Penn Station at 9:30 AM for Philadelphia 30th Street.",
                "notification_id": f"amtrak_tracker_{config_entry.entry_id}",
            }
        )


async def test_notification_custom_device_service(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is sent to custom notify service when selected."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "mobile_app_my_iphone",
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW), \
         patch.object(hass.services, "async_call", autospec=True) as mock_call:
        
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        mock_call.assert_any_call(
            "notify",
            "mobile_app_my_iphone",
            {
                "title": "Upcoming Amtrak Train 101",
                "message": "Departing New York Penn Station at 9:15 AM for Philadelphia 30th Street.",
                "data": {
                    "subtitle": "15 min delay",
                    "tag": f"amtrak_tracker_{config_entry.entry_id}",
                    "persistent": True,
                    "sticky": True,
                },
            }
        )


async def test_notification_dismiss_when_train_departed(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is cleared when upcoming train has departed."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "persistent_notification",
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW), \
         patch.object(hass.services, "async_call", autospec=True) as mock_call:
        
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Clear mock calls
        mock_call.reset_mock()

        # Update train status to Departed
        departed_trains = dict(MOCK_TRAINS)
        departed_trains["101"][0]["stations"][0]["status"] = "Departed"
        aioclient_mock.clear_requests()
        aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
        aioclient_mock.get(TRAINS_URL, json=departed_trains)

        coordinator = hass.data[DOMAIN]["coordinator"]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Notification should be dismissed
        mock_call.assert_any_call(
            "persistent_notification",
            "dismiss",
            {
                "notification_id": f"amtrak_tracker_{config_entry.entry_id}",
            }
        )


async def test_notification_dismiss_when_disabled_or_not_configured_day(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is dismissed/not sent when disabled or outside configured schedule days."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    # 1. Test not configured day (today is Friday/MOCK_NOW, but config is only Saturday)
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["saturday"],  # Only Saturday
            "start_time": "08:00",
            "end_time": "17:00",
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "persistent_notification",
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW), \
         patch.object(hass.services, "async_call", autospec=True) as mock_call:
        
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Verify no create call was made
        assert not any(call[0][0] == "persistent_notification" and call[0][1] == "create" for call in mock_call.mock_calls)

        # Unload
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

    # 2. Test notifications disabled
    config_entry_disabled = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
            CONF_NOTIFY_ENABLED: False,  # Disabled
            CONF_NOTIFY_SERVICE: "persistent_notification",
        },
    )
    config_entry_disabled.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW), \
         patch.object(hass.services, "async_call", autospec=True) as mock_call:
        
        assert await hass.config_entries.async_setup(config_entry_disabled.entry_id) is True
        await hass.async_block_till_done()

        # Verify no create call was made
        assert not any(call[0][0] == "persistent_notification" and call[0][1] == "create" for call in mock_call.mock_calls)


async def test_options_flow_and_reload(hass: HomeAssistant, aioclient_mock) -> None:
    """Test options flow updates config options and reloads the integration."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
            CONF_NOTIFY_ENABLED: False,
            CONF_NOTIFY_SERVICE: "persistent_notification",
        },
    )
    config_entry.add_to_hass(hass)

    # Initial setup (notifications disabled)
    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW), \
         patch.object(hass.services, "async_call", autospec=True) as mock_call:
        
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Verify no notification created
        assert not any(call[0][0] == "persistent_notification" and call[0][1] == "create" for call in mock_call.mock_calls)

        # Trigger options flow to enable notifications
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

        # Update options
        with patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True) as mock_reload:
            result2 = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    "days": ["friday"],
                    "start_time": "08:00",
                    "end_time": "17:00",
                    CONF_NOTIFY_ENABLED: True,
                    CONF_NOTIFY_SERVICE: "persistent_notification",
                },
            )
            await hass.async_block_till_done()
            assert result2["type"] == "create_entry"
            # Verify options reload was triggered
            mock_reload.assert_called_once_with(config_entry.entry_id)
