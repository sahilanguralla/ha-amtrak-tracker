import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Mock homeassistant modules and other external libraries before importing sensor
class MockSensorEntity:
    pass

class MockCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls

sys.modules["aiohttp"] = MagicMock()
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorEntity = MockSensorEntity
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = MockCoordinatorEntity
sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()

# Now import sensor after mocking
from custom_components.amtrak_tracker.sensor import AmtrakTrackerSensor, calculate_delay_minutes

def test_delay_calculation():
    # Test calculate_delay_minutes
    assert calculate_delay_minutes("2026-07-03T10:00:00-04:00", "2026-07-03T10:15:00-04:00") == 15
    assert calculate_delay_minutes("2026-07-03T10:00:00-04:00", "2026-07-03T09:45:00-04:00") == -15
    assert calculate_delay_minutes(None, "2026-07-03T10:15:00-04:00") is None

def test_sensor_tracking():
    # Setup mock config entry and coordinator
    mock_entry = MagicMock()
    mock_entry.data = {
        "origin": "NYP",
        "destination": "PHL",
        "days": ["monday", "friday"],
        "start_time": "08:00",
        "end_time": "17:00",
    }
    mock_entry.entry_id = "test_entry_id"

    mock_coordinator = MagicMock()
    # Mock API data with two trains:
    # Train 1: Scheduled Friday 09:00 (within duration)
    # Train 2: Scheduled Friday 12:00 (within duration)
    mock_coordinator.data = {
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

    stations_cache = {
        "NYP": {"name": "New York Penn Station"},
        "PHL": {"name": "Philadelphia 30th Street"}
    }

    # Initialize sensor
    sensor = AmtrakTrackerSensor(mock_coordinator, mock_entry, stations_cache)
    
    # 1. Initially, both trains are upcoming (Enroute at origin).
    # Active train should be Train 101.
    assert sensor.native_value == datetime.fromisoformat("2026-07-03T09:05:00-04:00")
    assert sensor.extra_state_attributes["train_number"] == "101"
    assert sensor.extra_state_attributes["matched_trains_count"] == 2
    assert sensor.extra_state_attributes["upcoming_trains_count"] == 2
    assert len(sensor.extra_state_attributes["upcoming_trains"]) == 2
    assert sensor.extra_state_attributes["upcoming_trains"][0]["train_number"] == "101"
    assert sensor.extra_state_attributes["upcoming_trains"][1]["train_number"] == "103"

    # 2. Now let's simulate Train 101 departing NYP (origin), but still en route to PHL (destination).
    mock_coordinator.data["101"][0]["stations"][0]["status"] = "Departed"
    sensor._update_internal_state()

    # Active train should STILL be Train 101 (actively tracking it).
    # But upcoming_trains should now only show Train 103 (since Train 101 has departed origin).
    assert sensor.native_value == datetime.fromisoformat("2026-07-03T09:05:00-04:00")
    assert sensor.extra_state_attributes["train_number"] == "101"
    assert sensor.extra_state_attributes["matched_trains_count"] == 2
    assert sensor.extra_state_attributes["upcoming_trains_count"] == 1
    assert len(sensor.extra_state_attributes["upcoming_trains"]) == 1
    assert sensor.extra_state_attributes["upcoming_trains"][0]["train_number"] == "103"

    # 3. Now let's simulate Train 101 arriving/departing PHL (destination).
    mock_coordinator.data["101"][0]["stations"][1]["status"] = "Departed"
    sensor._update_internal_state()

    # Active train should now switch to Train 103!
    assert sensor.native_value == datetime.fromisoformat("2026-07-03T12:00:00-04:00")
    assert sensor.extra_state_attributes["train_number"] == "103"
    assert sensor.extra_state_attributes["matched_trains_count"] == 2
    assert sensor.extra_state_attributes["upcoming_trains_count"] == 1
    assert len(sensor.extra_state_attributes["upcoming_trains"]) == 1
    assert sensor.extra_state_attributes["upcoming_trains"][0]["train_number"] == "103"

    # 4. Now let's simulate Train 103 also completing (departing destination).
    mock_coordinator.data["103"][0]["stations"][0]["status"] = "Departed"
    mock_coordinator.data["103"][0]["stations"][1]["status"] = "Departed"
    sensor._update_internal_state()

    # Active train should be None since all trains have finished.
    assert sensor.native_value is None
    assert sensor.extra_state_attributes["train_number"] is None
    assert sensor.extra_state_attributes["matched_trains_count"] == 2
    assert sensor.extra_state_attributes["upcoming_trains_count"] == 0
    assert len(sensor.extra_state_attributes["upcoming_trains"]) == 0

    print("All tracking logic tests passed successfully!")

if __name__ == "__main__":
    test_delay_calculation()
    test_sensor_tracking()
