"""Tests for notify target discovery and dispatch helpers."""

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amtrak_tracker.notify_targets import (
    async_send_notify,
    get_notify_target_options,
    is_mobile_app_push_target,
    mobile_app_entity_to_service_name,
)


def setup_mock_notify_services(hass: HomeAssistant) -> list[ServiceCall]:
    """Register mock notify services to capture calls."""
    calls: list[ServiceCall] = []

    @callback
    def mock_notify(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", "mobile_app_my_iphone", mock_notify)
    hass.services.async_register("notify", "send_message", mock_notify)
    return calls


async def test_get_notify_target_options_includes_entities(hass: HomeAssistant) -> None:
    """Test notify options include notify entities and legacy services."""
    config_entry = MockConfigEntry(
        domain="mobile_app",
        data={
            "device_name": "Monalis iPhone",
            "webhook_id": "abc123",
        },
    )
    config_entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "notify",
        "mobile_app",
        "device-123",
        config_entry=config_entry,
        suggested_object_id="monalis_iphone",
    )

    hass.services.async_register("notify", "mobile_app_monalis_iphone", lambda call: None)
    hass.services.async_register("notify", "mobile_app_legacy_phone", lambda call: None)

    options = get_notify_target_options(hass)
    values = {option["value"] for option in options}

    assert "persistent_notification" in values
    assert "notify.monalis_iphone" in values
    assert "mobile_app_legacy_phone" in values
    assert "mobile_app_monalis_iphone" not in values


async def test_mobile_app_entity_resolves_to_legacy_service(hass: HomeAssistant) -> None:
    """Test mobile app notify entities map to legacy notify services."""
    config_entry = MockConfigEntry(
        domain="mobile_app",
        data={
            "device_name": "My iPhone",
            "webhook_id": "abc123",
        },
    )
    config_entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get_or_create(
        "notify",
        "mobile_app",
        "device-123",
        config_entry=config_entry,
        suggested_object_id="my_iphone",
    )

    assert mobile_app_entity_to_service_name(hass, entity_entry) == "mobile_app_my_iphone"
    assert is_mobile_app_push_target(hass, "notify.my_iphone") is True
    assert is_mobile_app_push_target(hass, "mobile_app_my_iphone") is True
    assert is_mobile_app_push_target(hass, "generic_notify_service") is False


async def test_async_send_notify_via_mobile_app_entity(hass: HomeAssistant) -> None:
    """Test entity-based mobile app targets use the legacy notify service."""
    config_entry = MockConfigEntry(
        domain="mobile_app",
        data={
            "device_name": "My iPhone",
            "webhook_id": "abc123",
        },
    )
    config_entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "notify",
        "mobile_app",
        "device-123",
        config_entry=config_entry,
        suggested_object_id="my_iphone",
    )

    calls = setup_mock_notify_services(hass)

    await async_send_notify(
        hass,
        "notify.my_iphone",
        title="Upcoming Amtrak Train 101",
        message="Departing New York for Philadelphia (On time)",
        data={
            "tag": "amtrak_tracker_test",
            "live_update": True,
            "chronometer": True,
            "when": 1751546100,
        },
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].domain == "notify"
    assert calls[0].service == "mobile_app_my_iphone"
    assert calls[0].data == {
        "title": "Upcoming Amtrak Train 101",
        "message": "Departing New York for Philadelphia (On time)",
        "data": {
            "tag": "amtrak_tracker_test",
            "live_update": True,
            "chronometer": True,
            "when": 1751546100,
        },
    }
