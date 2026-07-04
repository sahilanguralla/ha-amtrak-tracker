"""Test sensor platform and tracking logic of Amtrak Tracker."""

from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amtrak_tracker.const import DOMAIN, STATIONS_URL, TRAINS_URL
from custom_components.amtrak_tracker.sensor import calculate_delay_minutes, AmtrakTrainSensor

MOCK_STATIONS = {
    "NYP": {"name": "New York Penn Station"},
    "PHL": {"name": "Philadelphia 30th Street"},
}

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
                    "dep": "2026-07-03T09:05:00-04:00",
                    "status": "Enroute",
                },
                {
                    "code": "PHL",
                    "schArr": "2026-07-03T10:30:00-04:00",
                    "arr": "2026-07-03T10:35:00-04:00",
                    "status": "Enroute",
                }
            ]
        }
    ],
    "103": [
        {
            "trainNum": "103",
            "routeName": "Keystone",
            "trainID": "103-1",
            "trainState": "Active",
            "lat": 40.1,
            "lon": -74.1,
            "velocity": 85.0,
            "stations": [
                {
                    "code": "NYP",
                    "schDep": "2026-07-03T12:00:00-04:00",
                    "dep": "2026-07-03T12:00:00-04:00",
                    "status": "Enroute",
                },
                {
                    "code": "PHL",
                    "schArr": "2026-07-03T13:30:00-04:00",
                    "arr": "2026-07-03T13:30:00-04:00",
                    "status": "Enroute",
                }
            ]
        }
    ]
}


def test_delay_calculation() -> None:
    """Test the calculate_delay_minutes helper."""
    assert calculate_delay_minutes("2026-07-03T10:00:00-04:00", "2026-07-03T10:15:00-04:00") == 15
    assert calculate_delay_minutes("2026-07-03T10:00:00-04:00", "2026-07-03T09:45:00-04:00") == -15
    assert calculate_delay_minutes(None, "2026-07-03T10:15:00-04:00") is None
    assert calculate_delay_minutes("2026-07-03T10:00:00-04:00", None) is None
    
    # Test invalid time format exception handling
    assert calculate_delay_minutes("invalid-time", "2026-07-03T10:15:00-04:00") is None


async def test_sensors_setup_and_update(hass: HomeAssistant, aioclient_mock) -> None:
    """Test full setup of the sensor platform and state updates."""
    # Mock API responses
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=MOCK_TRAINS)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
            "start_time": "08:00",
            "end_time": "17:00",
        },
    )
    config_entry.add_to_hass(hass)

    # Set up the integration entry
    assert await hass.config_entries.async_setup(config_entry.entry_id) is True
    await hass.async_block_till_done()

    # Check that 6 sensors are created in the entity registry
    ent_reg = er.async_get(hass)
    
    # We expect 3 departure sensors and 3 schedule sensors
    expected_entities = [
        "sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_time",
        "sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_delay",
        "sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_2_train_time",
        "sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_2_train_delay",
        "sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_3_train_time",
        "sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_3_train_delay",
    ]
    for entity_id in expected_entities:
        assert ent_reg.async_get(entity_id) is not None

    # Check 1st upcoming train state (Train 101 departure NYP is 09:05 AM)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_time")
    assert state is not None
    assert state.state == "9:05 AM"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #1 Train 101 Time"
    assert state.attributes["train_number"] == "101"
    assert state.attributes["upcoming_trains_count"] == 2

    # Check 1st schedule delay state (5 mins delay)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_delay")
    assert state is not None
    assert state.state == "5"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #1 Train 101 Delay"

    # Check 2nd upcoming train state (Train 103 departure NYP is 12:00 PM)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_2_train_time")
    assert state is not None
    assert state.state == "12:00 PM"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #2 Train 103 Time"

    # Check 3rd upcoming train (should be None/unknown since only 2 trains match)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_3_train_time")
    assert state is not None
    assert state.state == "unknown"  # Home Assistant represents None native value as "unknown" state
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #3 Train Time"

    # Trigger a coordinator update to simulate Train 101 departing NYP (origin)
    updated_trains = dict(MOCK_TRAINS)
    updated_trains["101"][0]["stations"][0]["status"] = "Departed"

    aioclient_mock.clear_requests()
    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=updated_trains)

    # Force coordinator data refresh
    coordinator = hass.data[DOMAIN]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Now Train 103 should be the 1st upcoming train
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_time")
    assert state is not None
    assert state.state == "12:00 PM"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #1 Train 103 Time"
    assert state.attributes["train_number"] == "103"

    # And the 2nd upcoming train should be unknown/None
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_2_train_time")
    assert state is not None
    assert state.state == "unknown"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #2 Train Time"


async def test_sensor_edge_cases(hass: HomeAssistant, aioclient_mock) -> None:
    """Test various edge cases and error handling paths in AmtrakTrainSensor."""
    # API data with various weird states/formats
    weird_trains = {
        "101": [
            # Train with missing stations key
            {
                "trainNum": "101",
                "routeName": "Keystone",
                "trainID": "101-1",
            },
            # Train with empty scheduled departure
            {
                "trainNum": "102",
                "stations": [
                    {"code": "NYP", "schDep": None, "status": "Enroute"},
                    {"code": "PHL", "schArr": "2026-07-03T10:30:00-04:00", "status": "Enroute"},
                ]
            },
            # Train with invalid scheduled departure format
            {
                "trainNum": "103",
                "stations": [
                    {"code": "NYP", "schDep": "invalid-date", "status": "Enroute"},
                    {"code": "PHL", "schArr": "2026-07-03T10:30:00-04:00", "status": "Enroute"},
                ]
            },
            # Train scheduled on a day not in config
            {
                "trainNum": "104",
                "stations": [
                    {"code": "NYP", "schDep": "2026-07-04T09:00:00-04:00", "status": "Enroute"}, # Saturday (not config)
                    {"code": "PHL", "schArr": "2026-07-04T10:30:00-04:00", "status": "Enroute"},
                ]
            },
            # Train outside time range
            {
                "trainNum": "105",
                "stations": [
                    {"code": "NYP", "schDep": "2026-07-03T20:00:00-04:00", "status": "Enroute"}, # 8:00 PM (out of range)
                    {"code": "PHL", "schArr": "2026-07-03T21:30:00-04:00", "status": "Enroute"},
                ]
            },
        ],
        "invalid_format": "not_a_list",  # Trigger line 145-146 (non-list train_list check)
    }

    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=weird_trains)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"], # Friday only
            "start_time": "08:00",
            "end_time": "17:00",
        },
    )
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id) is True
    await hass.async_block_till_done()

    # None of the weird trains should match and become upcoming
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_time")
    assert state is not None
    assert state.state == "unknown"


async def test_sensor_config_time_parse_error(hass: HomeAssistant) -> None:
    """Test behavior when the config entry contains an invalid start/end time."""
    # Handled by mock setup bypassing normal config validations
    coordinator = MagicMock()
    coordinator.data = {}
    
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "invalid",
            "end_time": "17:00",
        },
    )
    
    sensor = AmtrakTrainSensor(coordinator, config_entry, {}, 0, "departure")
    # Calling update internal state should log an error and return without raising exception
    with patch("custom_components.amtrak_tracker.sensor._LOGGER.error") as mock_log:
        sensor._update_internal_state()
        assert mock_log.called


async def test_device_info_property(hass: HomeAssistant) -> None:
    """Test device_info returns correct metadata."""
    coordinator = MagicMock()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="unique_entry_id",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
        },
    )
    stations_cache = {"NYP": {"name": "New York"}, "PHL": {"name": "Philadelphia"}}
    
    sensor = AmtrakTrainSensor(coordinator, config_entry, stations_cache, 0, "departure")
    device_info = sensor.device_info
    
    assert device_info["name"] == "New York to Philadelphia Amtrak Tracker"
    assert device_info["manufacturer"] == "Amtrak"


async def test_sensor_sorting_by_estimated_departure(hass: HomeAssistant, aioclient_mock) -> None:
    """Test that upcoming trains are sorted by their estimated departure time, not scheduled departure time."""
    delayed_trains = {
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
                        "schDep": "2026-07-03T10:00:00-04:00",
                        "dep": "2026-07-03T13:00:00-04:00",  # Delayed to 1:00 PM
                        "status": "Enroute",
                    },
                    {
                        "code": "PHL",
                        "schArr": "2026-07-03T11:30:00-04:00",
                        "arr": "2026-07-03T14:30:00-04:00",
                        "status": "Enroute",
                    }
                ]
            }
        ],
        "102": [
            {
                "trainNum": "102",
                "routeName": "Keystone",
                "trainID": "102-1",
                "trainState": "Active",
                "lat": 40.0,
                "lon": -74.0,
                "velocity": 80.0,
                "stations": [
                    {
                        "code": "NYP",
                        "schDep": "2026-07-03T11:00:00-04:00",
                        "dep": "2026-07-03T11:05:00-04:00",  # Est departure 11:05 AM
                        "status": "Enroute",
                    },
                    {
                        "code": "PHL",
                        "schArr": "2026-07-03T12:30:00-04:00",
                        "arr": "2026-07-03T12:35:00-04:00",
                        "status": "Enroute",
                    }
                ]
            }
        ],
        "103": [
            {
                "trainNum": "103",
                "routeName": "Keystone",
                "trainID": "103-1",
                "trainState": "Active",
                "lat": 40.0,
                "lon": -74.0,
                "velocity": 80.0,
                "stations": [
                    {
                        "code": "NYP",
                        "schDep": "2026-07-03T12:00:00-04:00",
                        "dep": "2026-07-03T12:00:00-04:00",  # Est departure 12:00 PM
                        "status": "Enroute",
                    },
                    {
                        "code": "PHL",
                        "schArr": "2026-07-03T13:30:00-04:00",
                        "arr": "2026-07-03T13:30:00-04:00",
                        "status": "Enroute",
                    }
                ]
            }
        ]
    }

    aioclient_mock.get(STATIONS_URL, json=MOCK_STATIONS)
    aioclient_mock.get(TRAINS_URL, json=delayed_trains)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="NYP to PHL Tracker",
        data={
            "origin": "NYP",
            "destination": "PHL",
            "days": ["friday"],
            "start_time": "08:00",
            "end_time": "17:00",
        },
    )
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id) is True
    await hass.async_block_till_done()

    # 1st upcoming train should be Train 102 (est departure 11:05 AM)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_1_train_time")
    assert state is not None
    assert state.state == "11:05 AM"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #1 Train 102 Time"
    assert state.attributes["train_number"] == "102"

    # 2nd upcoming train should be Train 103 (est departure 12:00 PM)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_2_train_time")
    assert state is not None
    assert state.state == "12:00 PM"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #2 Train 103 Time"
    assert state.attributes["train_number"] == "103"

    # 3rd upcoming train should be Train 101 (est departure 1:00 PM, even though scheduled 10:00 AM)
    state = hass.states.get("sensor.new_york_penn_station_to_philadelphia_30th_street_amtrak_tracker_3_train_time")
    assert state is not None
    assert state.state == "1:00 PM"
    assert state.name == "New York Penn Station to Philadelphia 30th Street Amtrak Tracker #3 Train 101 Time"
    assert state.attributes["train_number"] == "101"
