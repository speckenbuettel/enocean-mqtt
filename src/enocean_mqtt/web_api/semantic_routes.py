"""RuntimeService-backed semantic Web API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from time import monotonic
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from enocean_mqtt.datapoints import DatapointRegistry
from enocean_mqtt.datapoints.models import Datapoint
from enocean_mqtt.runtime.service import RuntimeService
from enocean_mqtt.web_api.configuration_routes import create_configuration_router

RuntimeServiceProvider = Callable[[], RuntimeService]
RuntimeCommandDispatcher = Callable[
    [str, dict[str, Any] | None],
    dict[str, Any],
]
RuntimeCommandDispatcherProvider = Callable[[], RuntimeCommandDispatcher | None]


def create_semantic_router(
    runtime_service_provider: RuntimeServiceProvider,
    runtime_command_dispatcher_provider: RuntimeCommandDispatcherProvider | None = None,
) -> APIRouter:
    """Create API routes that access semantic runtime data via RuntimeService."""

    router = APIRouter()
    router.include_router(create_configuration_router())

    def get_service() -> RuntimeService:
        return runtime_service_provider()

    def dispatch(command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        dispatcher = (
            runtime_command_dispatcher_provider()
            if runtime_command_dispatcher_provider is not None
            else None
        )
        if dispatcher is None:
            raise _not_implemented(
                "Runtime command dispatch is not configured for this API process.",
            )
        return dispatcher(command, payload)

    @router.get("/api/v1/devices")
    def get_api_devices() -> dict[str, Any]:
        service = get_service()
        return service.get_devices()

    @router.post("/api/v1/devices")
    def create_device(payload: dict[str, Any]) -> dict[str, Any]:
        device = payload.get("device", payload)
        if not isinstance(device, dict):
            raise HTTPException(status_code=422, detail="device must be an object")
        return dispatch("device.import", {"device": device})

    @router.post("/api/v1/devices/import")
    def import_devices(payload: dict[str, Any]) -> dict[str, Any]:
        devices = payload.get("devices")
        if not isinstance(devices, list) or not all(
            isinstance(device, dict) for device in devices
        ):
            raise HTTPException(status_code=422, detail="devices must be an array of objects")
        results = [
            dispatch("device.import", {"device": device})
            for device in devices
        ]
        return {"status": "accepted", "count": len(results), "results": results}

    @router.get("/api/v1/devices/export")
    def get_devices_export() -> dict[str, Any]:
        service = get_service()
        devices = service.get_devices()
        return {
            "format": "enocean-devices",
            "format_version": 1,
            "devices": devices.get("devices", []),
            "count": devices.get("count", 0),
            "issues": devices.get("issues", []),
        }

    @router.get("/api/v1/devices/{device_id}")
    def get_api_device(device_id: str) -> dict[str, Any]:
        service = get_service()
        device = service.get_device(device_id)

        if device is None:
            raise HTTPException(
                status_code=404,
                detail="Device not found",
            )

        return {
            "device": device,
            "issues": service.api_device_registry.issues,
        }

    @router.get("/api/v1/devices/{device_id}/datapoints")
    def get_device_datapoints(
        device_id: str,
        include_values: bool = False,
    ) -> dict[str, Any]:
        service = get_service()
        datapoints = service.datapoint_registry.by_device(device_id)

        if not datapoints:
            raise HTTPException(
                status_code=404,
                detail="Device datapoints not found",
            )

        if include_values:
            runtime = service.get_datapoint_runtime_registry()
            datapoint_payloads = [
                runtime.value_payload_for_datapoint(datapoint)
                for datapoint in datapoints
            ]
            issues = runtime.issues
        else:
            datapoint_payloads = [
                datapoint.to_api_dict()
                for datapoint in datapoints
            ]
            issues = service.datapoint_registry.issues

        return {
            "device_id": device_id,
            "datapoints": datapoint_payloads,
            "count": len(datapoint_payloads),
            "issues": issues,
        }

    @router.get("/api/v1/devices/{device_id}/state")
    def get_device_state(device_id: str) -> dict[str, Any]:
        service = get_service()
        state = service.get_device_state(device_id)

        if state is None:
            raise HTTPException(
                status_code=404,
                detail="Device state not found",
            )

        return {
            "device_id": device_id,
            "state": state,
        }

    @router.post("/api/v1/devices/{device_id}/republish")
    def republish_device(
        device_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise _not_implemented(
            "Device republish via HTTP is not implemented yet.",
        )

    @router.post("/api/v1/devices/{device_id}/teach-in")
    def teach_in_device(
        device_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            "device.teach_in",
            {"device_id": device_id, **({"teach_in": payload} if payload else {})},
        )

    @router.delete("/api/v1/devices/{device_id}")
    def delete_device(device_id: str) -> dict[str, Any]:
        return dispatch("device.delete", {"device_id": device_id})

    @router.get("/api/v1/datapoints")
    def get_datapoints(
        device_id: str | None = None,
        semantic_role: str | None = None,
        object_type: str | None = None,
        direction: str | None = None,
        readable: bool | None = None,
        writable: bool | None = None,
        data_type: str | None = None,
        tag: str | None = None,
        include_values: bool = False,
    ) -> dict[str, Any]:
        service = get_service()
        filtered_datapoints = _filter_datapoints(
            registry=service.datapoint_registry,
            device_id=device_id,
            semantic_role=semantic_role,
            object_type=object_type,
            direction=direction,
            readable=readable,
            writable=writable,
            data_type=data_type,
            tag=tag,
        )

        if include_values:
            runtime = service.get_datapoint_runtime_registry()
            datapoints = [
                runtime.value_payload_for_datapoint(datapoint)
                for datapoint in filtered_datapoints
            ]
            issues = runtime.issues
        else:
            datapoints = [
                datapoint.to_api_dict()
                for datapoint in filtered_datapoints
            ]
            issues = service.datapoint_registry.issues

        return {
            "datapoints": datapoints,
            "count": len(datapoints),
            "issues": issues,
        }

    @router.get("/api/v1/datapoints/tags")
    def get_datapoint_tags() -> dict[str, Any]:
        service = get_service()
        tags: dict[str, dict[str, Any]] = {}

        for datapoint in service.datapoint_registry.datapoints:
            metadata_tags = datapoint.metadata.get("tags")

            if isinstance(metadata_tags, str):
                tag_values = [metadata_tags]
            elif isinstance(metadata_tags, list):
                tag_values = [
                    str(tag)
                    for tag in metadata_tags
                    if str(tag).strip()
                ]
            else:
                tag_values = []

            for tag in tag_values:
                tag_key = tag.strip()
                entry = tags.setdefault(
                    tag_key,
                    {
                        "tag": tag_key,
                        "datapoints_count": 0,
                        "datapoints": [],
                    },
                )
                entry["datapoints_count"] += 1
                entry["datapoints"].append(datapoint.id)

        return {
            "tags": [
                tags[tag]
                for tag in sorted(tags)
            ],
            "count": len(tags),
        }

    @router.get("/api/v1/datapoints/stream")
    def stream_datapoint_values(
        request: Request,
        include_initial: bool = True,
        interval: float = Query(1.0, ge=0.2, le=60.0),
    ) -> StreamingResponse:
        return StreamingResponse(
            _datapoint_value_event_stream(
                request=request,
                runtime_service_provider=runtime_service_provider,
                include_initial=include_initial,
                interval=interval,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @router.get("/api/v1/datapoints/{datapoint_id}")
    def get_datapoint(
        datapoint_id: str,
        include_value: bool = False,
    ) -> dict[str, Any]:
        service = get_service()
        datapoint = service.datapoint_registry.get(datapoint_id)

        if datapoint is None:
            raise HTTPException(
                status_code=404,
                detail="Datapoint not found",
            )

        if include_value:
            runtime = service.get_datapoint_runtime_registry()
            return {
                "datapoint": runtime.value_payload_for_datapoint(datapoint),
                "issues": runtime.issues,
            }

        return {
            "datapoint": datapoint.to_api_dict(),
            "issues": service.datapoint_registry.issues,
        }

    @router.get("/api/v1/datapoints/{datapoint_id}/value")
    def get_datapoint_value(datapoint_id: str) -> dict[str, Any]:
        service = get_service()
        runtime = service.get_datapoint_runtime_registry()
        value = runtime.get_value(datapoint_id)

        if value is None:
            raise HTTPException(
                status_code=404,
                detail="Datapoint not found",
            )

        return {
            "value": value.to_api_dict(),
        }

    @router.post("/api/v1/datapoints/{datapoint_id}/value")
    def set_datapoint_value(
        datapoint_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise _not_implemented(
            "Datapoint write access via HTTP is not implemented yet.",
        )

    return router


def _not_implemented(message: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail={
            "status": "not_implemented",
            "message": message,
        },
    )


async def _datapoint_value_event_stream(
    *,
    request: Request,
    runtime_service_provider: RuntimeServiceProvider,
    include_initial: bool,
    interval: float,
) -> AsyncIterator[str]:
    seen: dict[str, str] = {}
    first_snapshot = True
    next_heartbeat = monotonic() + 15.0

    while True:
        if await request.is_disconnected():
            break

        emitted = 0
        service = runtime_service_provider()
        runtime = service.get_datapoint_runtime_registry()

        for datapoint in service.datapoint_registry.datapoints:
            value = runtime.get_value(datapoint.id)

            if value is None:
                continue

            payload = value.to_api_dict()
            fingerprint = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            )

            if first_snapshot and not include_initial:
                seen[datapoint.id] = fingerprint
                continue

            if (first_snapshot and include_initial) or seen.get(datapoint.id) != fingerprint:
                seen[datapoint.id] = fingerprint
                emitted += 1
                yield _sse_event("datapoint", payload)

        first_snapshot = False

        now = monotonic()
        if emitted == 0 and now >= next_heartbeat:
            next_heartbeat = now + 15.0
            yield ": keepalive\n\n"

        await asyncio.sleep(interval)


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(
        payload,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {data}\n\n"


def _filter_datapoints(
    *,
    registry: DatapointRegistry,
    device_id: str | None,
    semantic_role: str | None,
    object_type: str | None,
    direction: str | None,
    readable: bool | None,
    writable: bool | None,
    data_type: str | None,
    tag: str | None,
) -> list[Datapoint]:
    datapoints = registry.datapoints

    if device_id is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.device_id == device_id
        ]

    if semantic_role is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.semantic_role == semantic_role
        ]

    if object_type is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.object_type == object_type
        ]

    if direction is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.direction == direction
        ]

    if readable is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.readable is readable
        ]

    if writable is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.writable is writable
        ]

    if data_type is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if datapoint.data_type == data_type
        ]

    if tag is not None:
        datapoints = [
            datapoint
            for datapoint in datapoints
            if _datapoint_has_tag(datapoint, tag)
        ]

    return datapoints


def _datapoint_has_tag(datapoint: Datapoint, tag: str) -> bool:
    expected_tag = tag.strip()

    if not expected_tag:
        return False

    metadata_tags = datapoint.metadata.get("tags")

    if isinstance(metadata_tags, str):
        return metadata_tags.strip() == expected_tag

    if isinstance(metadata_tags, list):
        return any(
            str(metadata_tag).strip() == expected_tag
            for metadata_tag in metadata_tags
        )

    return False
