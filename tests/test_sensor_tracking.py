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
from custom_components.amtrak_tracker.sensor import AmtrakTrainSensor, calculate_delay_minutes

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

    # Initialize sensors (3 upcoming departure, 3 schedule)
    sensors = []
    for i in range(3):
        dep_sensor = AmtrakTrainSensor(mock_coordinator, mock_entry, stations_cache, i, "departure")
        sch_sensor = AmtrakTrainSensor(mock_coordinator, mock_entry, stations_cache, i, "schedule")
        sensors.append((dep_sensor, sch_sensor))
    
    # 1. Initially, both trains are upcoming (Enroute at origin).
    # 1st upcoming train (idx 0) should be Train 101.
    # 2nd upcoming train (idx 1) should be Train 103.
    # 3rd upcoming train (idx 2) should be None.
    
    # 1st Train Departure
    assert sensors[0][0].native_value == datetime.fromisoformat("2026-07-03T09:05:00-04:00")
    assert sensors[0][0].extra_state_attributes["train_number"] == "101"
    assert sensors[0][0].extra_state_attributes["matched_trains_count"] == 2
    assert sensors[0][0].extra_state_attributes["upcoming_trains_count"] == 2
    
    # 1st Train Schedule
    assert sensors[0][1].native_value == 5
    assert sensors[0][1].extra_state_attributes["train_number"] == "101"
    
    # 2nd Train Departure
    assert sensors[1][0].native_value == datetime.fromisoformat("2026-07-03T12:00:00-04:00")
    assert sensors[1][0].extra_state_attributes["train_number"] == "103"
    assert sensors[1][0].extra_state_attributes["matched_trains_count"] == 2
    assert sensors[1][0].extra_state_attributes["upcoming_trains_count"] == 2
    
    # 2nd Train Schedule
    assert sensors[1][1].native_value == 0
    assert sensors[1][1].extra_state_attributes["train_number"] == "103"
    
    # 3rd Train Departure & Schedule (should be None)
    assert sensors[2][0].native_value is None
    assert sensors[2][0].extra_state_attributes["train_number"] is None
    assert sensors[2][1].native_value is None
    assert sensors[2][1].extra_state_attributes["train_number"] is None

    # 2. Now let's simulate Train 101 departing NYP (origin), but still en route to PHL (destination).
    mock_coordinator.data["101"][0]["stations"][0]["status"] = "Departed"
    
    # Update internal state for all sensors
    for dep_sensor, sch_sensor in sensors:
        dep_sensor._update_internal_state()
        sch_sensor._update_internal_state()

    # Now, Train 101 is no longer upcoming. Train 103 becomes the 1st upcoming train.
    # 1st Train Departure should switch to Train 103.
    assert sensors[0][0].native_value == datetime.fromisoformat("2026-07-03T12:00:00-04:00")
    assert sensors[0][0].extra_state_attributes["train_number"] == "103"
    assert sensors[0][0].extra_state_attributes["matched_trains_count"] == 2
    assert sensors[0][0].extra_state_attributes["upcoming_trains_count"] == 1
    
    # 1st Train Schedule should switch to Train 103 (0 min delay)
    assert sensors[0][1].native_value == 0
    assert sensors[0][1].extra_state_attributes["train_number"] == "103"
    
    # 2nd Train Departure & Schedule should now be None
    assert sensors[1][0].native_value is None
    assert sensors[1][0].extra_state_attributes["train_number"] is None
    assert sensors[1][1].native_value is None
    assert sensors[1][1].extra_state_attributes["train_number"] is None

    # 3. Now let's simulate Train 103 also departing NYP.
    mock_coordinator.data["103"][0]["stations"][0]["status"] = "Departed"
    
    for dep_sensor, sch_sensor in sensors:
        dep_sensor._update_internal_state()
        sch_sensor._update_internal_state()

    # Both trains have departed origin. No upcoming trains remain.
    # All sensors should be None.
    for dep_sensor, sch_sensor in sensors:
        assert dep_sensor.native_value is None
        assert dep_sensor.extra_state_attributes["train_number"] is None
        assert sch_sensor.native_value is None
        assert sch_sensor.extra_state_attributes["train_number"] is None

    print("All tracking logic tests passed successfully!")

if __name__ == "__main__":
    test_delay_calculation()
    test_sensor_tracking()
