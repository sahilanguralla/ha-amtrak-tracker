"""Constants for the Amtrak Tracker integration."""

DOMAIN = "amtrak_tracker"

# Configuration keys
CONF_ORIGIN = "origin"
CONF_DESTINATION = "destination"
CONF_DAYS = "days"
CONF_START_TIME = "start_time"
CONF_END_TIME = "end_time"

# Defaults
DEFAULT_UPDATE_INTERVAL_SECONDS = 30

# API Endpoints
BASE_URL = "https://api.amtraker.com/v3"
STATIONS_URL = f"{BASE_URL}/stations"
TRAINS_URL = f"{BASE_URL}/trains"

# Days of the week definition
DAYS_OF_WEEK = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DAYS_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
