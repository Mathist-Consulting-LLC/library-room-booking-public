import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';
import {OUTCOMES, location, room, interval, availabilityRequest, bookingRequest,
  capabilities, operationResult, confirmationEvidence, evidenceMatches,
  bufferedInterval, withinWindow} from '@mathist/library-room-booking';
const fixtures = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const i = interval('2026-11-01T01:30:00-06:00', '2026-11-01T01:30:00-07:00', 'America/Denver');
const r = room(location('synthetic', 'site-a', i.timezone), 'room-a');
const request = bookingRequest(r, i, 'attempt-a');
test('same contract for synthetic alternate providers, injected dependencies', async () => {
  const denied = () => assert.fail('No transport or credentials needed');
  const dependencies = {transport: denied, credentials: denied, clock: () => '2026-01-01T00:00:00Z', contact: {}, configuration: {}, evidence: []};
  for (const name of ['synthetic', 'alternate']) {
    const provider = {
      capabilities: capabilities({availability: 'supported', confirmation: 'manual_only'}),
      async availability(req, deps) {
        assert.equal(req.room.location.provider, name);
        assert.equal(deps.clock(), '2026-01-01T00:00:00Z');
        return operationResult('available', req, {slots: [req.interval]});
      },
      async book(req, deps) { assert.equal(deps, dependencies); return operationResult('unsupported', req); }
    };
    const target = room(location(name, 'site-a', i.timezone), 'room-a');
    assert.equal(provider.capabilities.booking, 'unsupported');
    assert.equal(provider.capabilities.confirmation, 'manual_only');
    assert.deepEqual((await provider.availability(availabilityRequest(target, i), dependencies)).slots, [i]);
    assert.equal((await provider.book(bookingRequest(target, i, 'attempt-a'), dependencies)).outcome, 'unsupported');
    assert.throws(() => { provider.capabilities.booking = 'supported'; });
  }
  assert.throws(() => capabilities({unknown: 'supported'}));
  assert.throws(() => capabilities({booking: 'yes'}));
  assert.equal(capabilities(Object.create({booking: 'supported'})).booking, 'unsupported');
});
test('DST, buffers, inclusive booking windows', () => {
  for (const row of fixtures.valid) {
    const value = interval(row.start, row.end, row.timezone);
    const [start, end] = bufferedInterval(value, 15, 10);
    assert.equal((end-start)/60000, row.minutes+25);
    assert.equal(withinWindow(value, value), true);
    assert.equal(withinWindow(value, value, 1, 0), false);
    assert.equal(withinWindow(value, value, 0, 1), false);
  }
  const window = interval('2026-11-01T01:00:00-06:00', '2026-11-01T02:00:00-07:00', i.timezone);
  assert.equal(withinWindow(i, window, 15, 10), true);
  for (const row of fixtures.invalid) assert.throws(() => interval(row.start, row.end, row.timezone));
  for (const value of [-1, true, Infinity]) assert.throws(() => bufferedInterval(i, value));
  assert.throws(() => interval(i.end, i.start, i.timezone));
});
test('explicit outcomes, exact identity and evidence; immutable snapshots', () => {
  const e = confirmationEvidence(request, 'booking-a', 'synthetic-origin', 'receipt-a', true);
  assert.equal(operationResult('confirmed', request, {bookingId: 'booking-a', evidence: e, expectedOrigin: 'synthetic-origin'}).outcome, 'confirmed');
  for (const outcome of OUTCOMES.filter(o => o !== 'confirmed')) assert.equal(operationResult(outcome, request).outcome, outcome);
  for (const bad of [null, {...e, verified: false}, {...e, bookingId: 'other'}, {...e, origin: 'other'},
    {...e, request: {...request, attemptId: 'other'}}, {...e, request: {...request, room: {...r, roomId: 'other'}}},
    {...e, request: {...request, interval: interval('2026-11-01T03:00:00-07:00', '2026-11-01T04:00:00-07:00', i.timezone)}}]) {
    assert.equal(evidenceMatches(bad, request, 'booking-a', 'synthetic-origin'), false);
    assert.throws(() => operationResult('confirmed', request, {bookingId: 'booking-a', evidence: bad, expectedOrigin: 'synthetic-origin'}));
  }
  assert.throws(() => operationResult('confirmed', request));
  assert.throws(() => operationResult('success', request));
  assert.throws(() => operationResult('unsupported', request, {slots: [i]}));
  assert.throws(() => operationResult('available', request, {slots: [interval('2026-11-01T03:00:00-07:00', '2026-11-01T04:00:00-07:00', i.timezone)]}));
  const input = {...request, room: {...r}};
  const result = operationResult('unknown_after_submit', input);
  input.room.roomId = 'changed';
  assert.equal(result.request.room.roomId, 'room-a');
});

test('timezone must be explicit and named', () => {
  const start = '2026-01-01T12:00:00Z';
  const end = '2026-01-01T13:00:00Z';
  assert.throws(() => interval(start, end), /Explicit named timezone/);
  assert.throws(() => location('synthetic', 'location-a', '+01:00'), /Explicit named timezone/);
  assert.equal(interval(start, end, 'UTC').timezone, 'UTC');
});
