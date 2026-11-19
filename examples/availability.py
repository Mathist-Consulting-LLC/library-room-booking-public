"""Offline LibCal discovery/availability; transport never connects."""
from datetime import datetime, timezone
import json
from library_room_booking import Location, Room, Interval, AvailabilityRequest, Dependencies, Outcome
from library_room_booking.libcal import LibCalAdapter, Response

calls = []
def transport(*, method, url, headers, body):
    calls.append(method)
    if method == 'GET':
        return Response(200, url, 'var resources = [{eid:30,gid:20,lid:10,capacity:6,title:"Study One"}];')
    assert url.endswith('/spaces/availability/grid')
    return Response(200, url, json.dumps({'slots': [{'itemId': '30',
        'start': '2026-12-01 18:00:00', 'end': '2026-12-01 19:00:00'}]}))

location = Location('synthetic-libcal', '10', 'America/Denver')
deps = Dependencies(transport, lambda: None, lambda: datetime.now(timezone.utc), {},
    {'provider': location.provider, 'base_url': 'https://library.example.invalid',
     'availability_path': '/spaces?lid=10&gid=20', 'location_id': 10,
     'group_id': 20, 'timezone': location.timezone})
adapter = LibCalAdapter(claim_submission=lambda request: False)
found = adapter.discover(location, deps)
assert found.outcome is Outcome.AVAILABLE
request = AvailabilityRequest(found.resources[0].room,
    Interval('2026-12-01T18:00:00-07:00', '2026-12-01T19:00:00-07:00', location.timezone))
result = adapter.availability(request, deps)
assert result.outcome is Outcome.AVAILABLE
assert calls == ['GET', 'GET', 'POST']  # POST is the read-side grid query, not booking.
print('room=' + request.room.room_id + '; outcome=' + result.outcome.value + '; calls=3')
try:
    Interval('2026-12-01T18:00:00+00:00', '2026-12-01T19:00:00+00:00', location.timezone)
except ValueError:
    print('invalid offset rejected; no booking attempted')
else:
    raise AssertionError('Expected offset validation')
