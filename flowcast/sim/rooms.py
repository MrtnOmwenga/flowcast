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
    # Cross-flow: a filter wall across one end blows air horizontally through the room to low
    # return grilles on the opposite wall, as in horizontal-flow clean areas.
    "cross": Room(inlets=(("x1", 0.0, 0.0, 4.0, 3.0),), outlets=(("x0", 0.4, 0.0, 3.2, 0.4),), ach_range=(10.0, 60.0)),
    # A fan-cooled control cabinet, 2.0 m tall, 0.8 m wide and 0.4 m deep, laid on its back so
    # that its mounting plate is the "floor": x runs up the cabinet, y across it, z out from
    # the plate. Air enters through a filter fan at the bottom and leaves at the top. The fan
    # range is 200 to 1,000 cubic metres an hour.
    "cabinet": Room(
        size=(2.0, 0.8, 0.4), cell=0.05, kind="cabinet",
        inlets=(("x0", 0.2, 0.1, 0.4, 0.2),), outlets=(("x1", 0.2, 0.1, 0.4, 0.2),),
        ach_range=(312.5, 1562.5),
    ),
}
DEFAULT_ROOM = "panels"
