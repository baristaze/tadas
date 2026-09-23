"""One router module per hosted namespace, mounted under /v1 by the app."""

from fastapi import APIRouter

from tadas.services.api.realtime import socket
from tadas.services.api.routers import admin, billing, events, tasks, tenancy


def all_routers() -> list[APIRouter]:
    return [
        tenancy.router,
        admin.router,
        tasks.router,
        events.router,
        billing.router,
        socket.router,
    ]
