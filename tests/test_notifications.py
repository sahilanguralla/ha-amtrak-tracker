"""Test upcoming train notifications for Amtrak Tracker."""

from datetime import datetime
from unittest.mock import patch

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amtrak_tracker.const import (
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_LIVE_ACTIVITY,
    DOMAIN,
    STATIONS_URL,
    TRAINS_URL,
)
from custom_components.amtrak_tracker.notifications import async_dismiss_notifications, async_update_train_notifications

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


def setup_mock_services(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    """Register mock services to capture calls."""
    calls = {
        "persistent_notification_create": [],
        "persistent_notification_dismiss": [],
        "notify": [],
    }

    @callback
    def mock_pn_create(call: ServiceCall) -> None:
        calls["persistent_notification_create"].append(call)
        notifications = hass.data.setdefault("persistent_notification", {})
        nid = call.data.get("notification_id")
        if nid:
            notifications[nid] = {
                "notification_id": nid,
                "message": call.data.get("message"),
                "title": call.data.get("title"),
                "created_at": dt_util.now(),
            }

    @callback
    def mock_pn_dismiss(call: ServiceCall) -> None:
        calls["persistent_notification_dismiss"].append(call)
        notifications = hass.data.setdefault("persistent_notification", {})
        nid = call.data.get("notification_id")
        if nid in notifications:
            del notifications[nid]

    @callback
    def mock_notify(call: ServiceCall) -> None:
        calls["notify"].append(call)

    hass.services.async_register("persistent_notification", "create", mock_pn_create)
    hass.services.async_register("persistent_notification", "dismiss", mock_pn_dismiss)
    hass.services.async_register("notify", "persistent_notification", mock_notify)
    hass.services.async_register("notify", "mobile_app_my_iphone", mock_notify)

    return calls


async def test_notification_creation_and_deduplication(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is created, updated on changes, and skipped on duplicate data."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        # Setup entry
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Notification should be created
        assert len(service_calls["persistent_notification_create"]) == 1
        assert service_calls["persistent_notification_create"][0].data == {
            "title": "Upcoming Train 101 (15 min delay)",
            "message": "Departing New York Penn Station at 9:15 AM for Philadelphia 30th Street.",
            "notification_id": f"amtrak_tracker_{config_entry.entry_id}",
        }
        
        service_calls["persistent_notification_create"].clear()

        # Update coordinator (data unchanged)
        coordinator = hass.data[DOMAIN]["coordinator"]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # No new notification should be sent (de-duplication)
        assert len(service_calls["persistent_notification_create"]) == 0

        # Update coordinator with new delay (30 mins delay)
        import copy
        updated_trains = copy.deepcopy(MOCK_TRAINS)
        updated_trains["101"][0]["stations"][0]["dep"] = "2026-07-03T09:30:00-04:00"
        aioclient_mock.clear_requests()
        aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
        aioclient_mock.get(TRAINS_URL, json=updated_trains)

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Notification should be updated
        assert len(service_calls["persistent_notification_create"]) == 1
        assert service_calls["persistent_notification_create"][0].data == {
            "title": "Upcoming Train 101 (30 min delay)",
            "message": "Departing New York Penn Station at 9:30 AM for Philadelphia 30th Street.",
            "notification_id": f"amtrak_tracker_{config_entry.entry_id}",
        }


async def test_notification_custom_device_service(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is sent to custom notify service when selected."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Notification should be sent to mobile_app_my_iphone notify service
        assert len(service_calls["notify"]) == 1
        expected_when = int(datetime.fromisoformat("2026-07-03T09:15:00-04:00").timestamp())
        assert service_calls["notify"][0].data == {
            "title": "Upcoming Amtrak Train 101",
            "message": "Departing New York Penn Station for Philadelphia 30th Street (15 min delay)",
            "data": {
                "tag": f"amtrak_tracker_{config_entry.entry_id}",
                "subtitle": "15 min delay",
                "persistent": True,
                "sticky": True,
                "live_update": True,
                "chronometer": True,
                "when": expected_when,
            },
        }


async def test_notification_custom_device_service_no_live_activity(hass: HomeAssistant, aioclient_mock) -> None:
    """Test regular high priority notification is sent to custom notify service when live activity is disabled."""
    from custom_components.amtrak_tracker.const import CONF_NOTIFY_LIVE_ACTIVITY

    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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
            CONF_NOTIFY_LIVE_ACTIVITY: False,
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Notification should be sent to mobile_app_my_iphone notify service with regular high priority payload
        assert len(service_calls["notify"]) == 1
        assert service_calls["notify"][0].data == {
            "title": "Upcoming Amtrak Train 101",
            "message": "Departing New York Penn Station at 9:15 AM for Philadelphia 30th Street.",
            "data": {
                "tag": f"amtrak_tracker_{config_entry.entry_id}",
                "priority": "high",
                "ttl": 0,
                "push": {
                    "interruption-level": "time-sensitive",
                },
            },
        }


async def test_notification_mobile_app_entity_target(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is sent via legacy service when a notify entity is selected."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

    mobile_app_entry = MockConfigEntry(
        domain="mobile_app",
        data={
            "device_name": "My iPhone",
            "webhook_id": "abc123",
        },
    )
    mobile_app_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "notify",
        "mobile_app",
        "device-123",
        config_entry=mobile_app_entry,
        suggested_object_id="my_iphone",
    )

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
            CONF_NOTIFY_SERVICE: "notify.my_iphone",
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        assert len(service_calls["notify"]) == 1
        expected_when = int(datetime.fromisoformat("2026-07-03T09:15:00-04:00").timestamp())
        assert service_calls["notify"][0].service == "mobile_app_my_iphone"
        assert service_calls["notify"][0].data == {
            "title": "Upcoming Amtrak Train 101",
            "message": "Departing New York Penn Station for Philadelphia 30th Street (15 min delay)",
            "data": {
                "tag": f"amtrak_tracker_{config_entry.entry_id}",
                "subtitle": "15 min delay",
                "persistent": True,
                "sticky": True,
                "live_update": True,
                "chronometer": True,
                "when": expected_when,
            },
        }


async def test_notification_non_mobile_app_fallback_service(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is sent with standard payload for non-mobile-app custom service."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

    @callback
    def mock_fallback_notify(call: ServiceCall) -> None:
        service_calls["notify"].append(call)

    hass.services.async_register("notify", "generic_notify_service", mock_fallback_notify)

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
            CONF_NOTIFY_SERVICE: "generic_notify_service",
        },
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Notification should be sent to generic_notify_service notify service with standard data
        assert len(service_calls["notify"]) == 1
        assert service_calls["notify"][0].data == {
            "title": "Upcoming Amtrak Train 101",
            "message": "Departing New York Penn Station at 9:15 AM for Philadelphia 30th Street.",
            "data": {
                "subtitle": "15 min delay",
                "tag": f"amtrak_tracker_{config_entry.entry_id}",
                "persistent": True,
                "sticky": True,
            },
        }


async def test_notification_dismiss_when_train_departed(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is cleared when upcoming train has departed."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        service_calls["persistent_notification_create"].clear()
        service_calls["persistent_notification_dismiss"].clear()

        # Update train status to Departed
        import copy
        departed_trains = copy.deepcopy(MOCK_TRAINS)
        departed_trains["101"][0]["stations"][0]["status"] = "Departed"
        aioclient_mock.clear_requests()
        aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
        aioclient_mock.get(TRAINS_URL, json=departed_trains)

        coordinator = hass.data[DOMAIN]["coordinator"]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Notification should be dismissed
        assert len(service_calls["persistent_notification_dismiss"]) == 1
        assert service_calls["persistent_notification_dismiss"][0].data == {
            "notification_id": f"amtrak_tracker_{config_entry.entry_id}",
        }


async def test_notification_dismiss_when_disabled_or_not_configured_day(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is dismissed/not sent when disabled or outside configured schedule days."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Verify no create call was made
        assert len(service_calls["persistent_notification_create"]) == 0

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

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry_disabled.entry_id) is True
        await hass.async_block_till_done()

        # Verify no create call was made
        assert len(service_calls["persistent_notification_create"]) == 0


async def test_options_flow_and_reload(hass: HomeAssistant, aioclient_mock) -> None:
    """Test options flow updates config options and reloads the integration."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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
    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Verify no notification created
        assert len(service_calls["persistent_notification_create"]) == 0

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
                    CONF_NOTIFY_LIVE_ACTIVITY: False,
                },
            )
            await hass.async_block_till_done()
            assert result2["type"] == "create_entry"
            # Verify options reload was triggered
            mock_reload.assert_called_once_with(config_entry.entry_id)
            assert config_entry.options.get(CONF_NOTIFY_LIVE_ACTIVITY) is False


async def test_notification_recreation_on_dismiss(hass: HomeAssistant, aioclient_mock) -> None:
    """Test notification is recreated if dismissed but the train is still upcoming."""
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    service_calls = setup_mock_services(hass)

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

    with patch("homeassistant.util.dt.now", return_value=MOCK_NOW):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

        # Notification should be created
        assert len(service_calls["persistent_notification_create"]) == 1
        service_calls["persistent_notification_create"].clear()

        # Simulate user dismissing the notification manually
        nid = f"amtrak_tracker_{config_entry.entry_id}"
        notifications = hass.data.get("persistent_notification", {})
        assert nid in notifications
        del notifications[nid]

        # Update coordinator (data unchanged)
        coordinator = hass.data[DOMAIN]["coordinator"]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Notification should be recreated since it was dismissed
        assert len(service_calls["persistent_notification_create"]) == 1
        assert service_calls["persistent_notification_create"][0].data == {
            "title": "Upcoming Train 101 (15 min delay)",
            "message": "Departing New York Penn Station at 9:15 AM for Philadelphia 30th Street.",
            "notification_id": nid,
        }
