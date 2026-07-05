"""Helpers for discovering and sending Home Assistant notifications."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

NOTIFY_DOMAIN = "notify"
PERSISTENT_NOTIFICATION = "persistent_notification"
MOBILE_APP_DOMAIN = "mobile_app"
MOBILE_APP_DEVICE_NAME = "device_name"
MOBILE_APP_WEBHOOK_ID = "webhook_id"
LEGACY_NOTIFY_SERVICES_TO_SKIP = frozenset(
    {PERSISTENT_NOTIFICATION, "send_message", "notify"}
)


def get_notify_target_options(hass: HomeAssistant) -> list[dict[str, str]]:
    """Return notify destination options for config/options flows."""
    options: list[dict[str, str]] = [
        {
            "value": PERSISTENT_NOTIFICATION,
            "label": "Persistent Notification (built-in)",
        }
    ]

    entity_registry = er.async_get(hass)
    covered_legacy_services: set[str] = set()

    for entity_entry in entity_registry.entities.values():
        if entity_entry.domain != NOTIFY_DOMAIN:
            continue
        display_name = (
            entity_entry.name
            or entity_entry.original_name
            or entity_entry.entity_id
        )
        options.append(
            {
                "value": entity_entry.entity_id,
                "label": f"{display_name} ({entity_entry.entity_id})",
            }
        )
        if entity_entry.platform == MOBILE_APP_DOMAIN:
            service_name = mobile_app_entity_to_service_name(hass, entity_entry)
            if service_name:
                covered_legacy_services.add(service_name)

    for service_name in sorted(
        hass.services.async_services().get(NOTIFY_DOMAIN, {}).keys()
    ):
        if service_name in LEGACY_NOTIFY_SERVICES_TO_SKIP:
            continue
        if service_name in covered_legacy_services:
            continue
        options.append(
            {
                "value": service_name,
                "label": f"Notify service: {service_name}",
            }
        )

    return options


def is_mobile_app_push_target(hass: HomeAssistant, target: str) -> bool:
    """Return True when the target can receive mobile app push payloads."""
    if target.startswith(f"{NOTIFY_DOMAIN}."):
        entity_entry = er.async_get(hass).async_get(target)
        if entity_entry:
            return entity_entry.platform == MOBILE_APP_DOMAIN
        target = target.removeprefix(f"{NOTIFY_DOMAIN}.")
    return target in _mobile_app_registered_targets(hass) or target.startswith("mobile_app_")


def mobile_app_entity_to_service_name(
    hass: HomeAssistant, entity_entry: er.RegistryEntry
) -> str | None:
    """Map a mobile_app notify entity to its legacy notify service name."""
    config_entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)

    registered_target = _mobile_app_entity_to_registered_service_name(hass, config_entry)
    if registered_target:
        return registered_target

    notify_services = hass.services.async_services().get(NOTIFY_DOMAIN, {})
    entity_object_id = entity_entry.entity_id.removeprefix(f"{NOTIFY_DOMAIN}.")
    entity_id_service_name = slugify(f"{MOBILE_APP_DOMAIN}_{entity_object_id}")
    if entity_id_service_name in notify_services:
        return entity_id_service_name

    if not config_entry:
        return entity_id_service_name

    if device_name := config_entry.data.get(MOBILE_APP_DEVICE_NAME):
        return slugify(f"{MOBILE_APP_DOMAIN}_{device_name}")

    return entity_id_service_name


def _mobile_app_registered_targets(hass: HomeAssistant) -> dict[str, Any]:
    """Return mobile_app legacy notify service targets registered in Home Assistant."""
    notify_service = hass.data.get(MOBILE_APP_DOMAIN, {}).get("notify")
    return getattr(notify_service, "registered_targets", {}) or {}


def _mobile_app_entity_to_registered_service_name(
    hass: HomeAssistant,
    config_entry: Any | None,
) -> str | None:
    """Resolve a mobile_app notify entity using Home Assistant's registered target map."""
    if not config_entry:
        return None

    webhook_id = config_entry.data.get(MOBILE_APP_WEBHOOK_ID)
    if not webhook_id:
        return None

    for service_name, target_webhook_id in _mobile_app_registered_targets(hass).items():
        if target_webhook_id == webhook_id:
            return service_name

    return None


def resolve_notify_service_name(hass: HomeAssistant, target: str) -> str:
    """Resolve a configured notify target to a legacy notify service name."""
    if not target.startswith(f"{NOTIFY_DOMAIN}."):
        return target

    entity_entry = er.async_get(hass).async_get(target)
    if not entity_entry:
        return target.removeprefix(f"{NOTIFY_DOMAIN}.")

    if entity_entry.platform == MOBILE_APP_DOMAIN:
        service_name = mobile_app_entity_to_service_name(hass, entity_entry)
        if not service_name:
            return target.removeprefix(f"{NOTIFY_DOMAIN}.")
        return service_name

    return target


async def async_send_notify(
    hass: HomeAssistant,
    target: str,
    *,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Send a notification to the configured target."""
    if target == PERSISTENT_NOTIFICATION:
        payload: dict[str, Any] = {
            "title": title,
            "message": message,
        }
        if data and (notification_id := data.get("notification_id")):
            payload["notification_id"] = notification_id
        await hass.services.async_call(
            PERSISTENT_NOTIFICATION,
            "create",
            payload,
            blocking=True,
        )
        return

    if target.startswith(f"{NOTIFY_DOMAIN}."):
        entity_entry = er.async_get(hass).async_get(target)
        if entity_entry and entity_entry.platform == MOBILE_APP_DOMAIN:
            service_name = resolve_notify_service_name(hass, target)
            payload = {"title": title, "message": message}
            if data:
                payload["data"] = data
            await hass.services.async_call(NOTIFY_DOMAIN, service_name, payload, blocking=True)
            return

        payload = {
            "title": title,
            "message": message,
        }
        await hass.services.async_call(
            NOTIFY_DOMAIN,
            "send_message",
            payload,
            target={"entity_id": target},
            blocking=True,
        )
        return

    payload = {"title": title, "message": message}
    if data:
        payload["data"] = data
    await hass.services.async_call(NOTIFY_DOMAIN, target, payload, blocking=True)


async def async_clear_notify(
    hass: HomeAssistant,
    target: str,
    *,
    tag: str,
    notification_id: str | None = None,
) -> None:
    """Clear or dismiss a notification for the configured target."""
    if target == PERSISTENT_NOTIFICATION:
        await hass.services.async_call(
            PERSISTENT_NOTIFICATION,
            "dismiss",
            {"notification_id": notification_id},
            blocking=True,
        )
        return
    if not is_mobile_app_push_target(hass, target):
        return

    service_name = resolve_notify_service_name(hass, target)

    await hass.services.async_call(
        NOTIFY_DOMAIN,
        service_name,
        {
            "message": "clear_notification",
            "data": {"tag": tag},
        },
        blocking=True,
    )
