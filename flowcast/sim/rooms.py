"""The room designs Flowcast has models for. Each design is trained separately."""

from __future__ import annotations

from .spec import Room

ROOMS: dict[str, Room] = {
    # Four ceiling supply panels and low extracts on one end wall: the usual arrangement
    # for a mixed-flow cleanroom of ISO class 7 or 8.
    "panels": Room(),
    # A filter ceiling over the whole room, with low extracts on both end walls. Air moves
    # down through the room like a piston, as in higher-grade cleanrooms, which are run at
    # far higher air change rates.
    "ceiling": Room(supplies=((0.0, 0.0, 6.0, 4.0),), extract_walls=("x0", "x1"), ach_range=(20.0, 120.0)),
}
DEFAULT_ROOM = "panels"
