"""Run unchanged against installed wheel and rebuilt sdist, outside source cwd."""
import json
from pathlib import Path
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from library_room_booking import (
    Location, Room, Interval, AvailabilityRequest, BookingRequest, Dependencies,
    OperationResult, Outcome, ConfirmationEvidence, capabilities, evidence_matches,
    buffered_interval, within_window,
)

PROVIDERS = json.loads(Path(sys.argv[-1]).with_name("providers.json").read_text())["cases"]
FIXTURES = json.loads(Path(sys.argv.pop()).read_text())


class SyntheticAvailabilityProvider:
    def __init__(self, name):
        self.name = name
        self.capabilities = capabilities(availability="supported", confirmation="manual_only")

    def availability(self, request, dependencies):
        assert request.room.location.provider == self.name
        assert dependencies.clock() == datetime(2026, 1, 1, tzinfo=timezone.utc)
        return OperationResult(Outcome.AVAILABLE, request, (request.interval,))

    def book(self, request, dependencies):
        return OperationResult(Outcome.UNSUPPORTED, request)


class Contracts(unittest.TestCase):
    def test_shared_provider_identity_and_results(self):
        for row in PROVIDERS:
            l = row['room']['location']
            room = Room(Location(l['provider'], l['locationId'], l['timezone']), row['room']['roomId'])
            i = Interval(**row['interval'])
            request = AvailabilityRequest(room, i)
            result = OperationResult(Outcome(row['outcome']), request, (i,))
            self.assertEqual(result.request.room.room_id, row['room']['roomId'])
            self.assertEqual(result.request.room.location.location_id, row['configuration']['locationId'])
            self.assertEqual(result.outcome.value, row['outcome'])
            self.assertEqual(result.slots, (i,))

    def setUp(self):
        self.interval = Interval("2026-11-01T01:30:00-06:00", "2026-11-01T01:30:00-07:00", "America/Denver")
        self.room = Room(Location("synthetic", "site-a", "America/Denver"), "room-a")
        self.request = BookingRequest(self.room, self.interval, "attempt-a")

    def test_same_contract_for_alternate_providers(self):
        def denied(*args): self.fail("No transport or credentials needed")
        deps = Dependencies(denied, denied, lambda: datetime(2026, 1, 1, tzinfo=timezone.utc), {}, {})
        for name in ("synthetic", "alternate"):
            provider = SyntheticAvailabilityProvider(name)
            room = Room(Location(name, "site-a", "America/Denver"), "room-a")
            request = BookingRequest(room, self.interval, "attempt-a")
            self.assertEqual(provider.capabilities["booking"], "unsupported")
            self.assertEqual(provider.capabilities["confirmation"], "manual_only")
            self.assertEqual(provider.availability(AvailabilityRequest(room, self.interval), deps).slots, (self.interval,))
            self.assertEqual(provider.book(request, deps).outcome, Outcome.UNSUPPORTED)
        with self.assertRaises(ValueError): capabilities(unknown="supported")
        with self.assertRaises(ValueError): capabilities(booking="yes")
        with self.assertRaises(TypeError): provider.capabilities["booking"] = "supported"

    def test_dst_buffers_and_windows(self):
        for row in FIXTURES['valid']:
            interval = Interval(**{k: row[k] for k in ('start', 'end', 'timezone')})
            start, end = buffered_interval(interval, 15, 10)
            self.assertEqual((end-start).total_seconds()/60, row['minutes']+25)
            self.assertTrue(within_window(interval, interval))
            self.assertFalse(within_window(interval, interval, setup_minutes=1))
            self.assertFalse(within_window(interval, interval, cleanup_minutes=1))
        window = Interval('2026-11-01T01:00:00-06:00', '2026-11-01T02:00:00-07:00', 'America/Denver')
        self.assertTrue(within_window(self.interval, window, setup_minutes=15, cleanup_minutes=10))
        for row in FIXTURES['invalid']:
            with self.assertRaises(ValueError): Interval(**row)
        with self.assertRaises(ValueError): buffered_interval(self.interval, -1, 0)
        with self.assertRaises(ValueError): buffered_interval(self.interval, True, 0)
        with self.assertRaises(ValueError): Interval(self.interval.end, self.interval.start, self.interval.timezone)

    def test_outcomes_and_exact_evidence(self):
        evidence = ConfirmationEvidence(self.request, 'booking-a', 'synthetic-origin', 'receipt-a', True)
        result = OperationResult(Outcome.CONFIRMED, self.request, booking_id='booking-a', evidence=evidence, expected_origin='synthetic-origin')
        self.assertEqual(result.outcome, Outcome.CONFIRMED)
        for outcome in Outcome:
            if outcome is not Outcome.CONFIRMED:
                self.assertEqual(OperationResult(outcome, self.request).outcome, outcome)
        for bad in (replace(evidence, verified=False), replace(evidence, booking_id='other'),
                    replace(evidence, origin='other'), replace(evidence, request=replace(self.request, attempt_id='other')),
                    replace(evidence, request=replace(self.request, room=replace(self.room, room_id='other'))),
                    replace(evidence, request=replace(self.request, interval=Interval('2026-11-01T03:00:00-07:00', '2026-11-01T04:00:00-07:00', 'America/Denver'))), None):
            self.assertFalse(evidence_matches(bad, self.request, 'booking-a', 'synthetic-origin'))
            with self.assertRaises(ValueError):
                OperationResult(Outcome.CONFIRMED, self.request, booking_id='booking-a', evidence=bad, expected_origin='synthetic-origin')
        with self.assertRaises(ValueError): OperationResult(Outcome.CONFIRMED, self.request)
        with self.assertRaises(ValueError): OperationResult('confirmed', self.request)
        with self.assertRaises(ValueError): OperationResult(Outcome.UNSUPPORTED, self.request, (self.interval,))
        with self.assertRaises(ValueError):
            OperationResult(Outcome.AVAILABLE, self.request, (Interval('2026-11-01T03:00:00-07:00', '2026-11-01T04:00:00-07:00', 'America/Denver'),))


if __name__ == '__main__': unittest.main()
