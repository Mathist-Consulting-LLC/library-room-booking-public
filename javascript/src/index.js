/** Provider-neutral contract factories. No transport, state or provider defaults. */
export const OUTCOMES = Object.freeze(['available', 'unavailable', 'unsupported', 'manual_only',
  'authentication_required', 'deferred', 'pending_confirmation', 'confirmed', 'rejected',
  'failed_before_submit', 'unknown_after_submit']);
export const OPERATIONS = Object.freeze(['discovery', 'availability', 'booking', 'confirmation', 'modification', 'cancellation']);
const SUPPORT = ['supported', 'unsupported', 'manual_only', 'authentication_required'];
function text(value) {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim()) throw new TypeError('Expected exact identity.');
  return value;
}
function namedTimezone(timezone) {
  if (typeof timezone !== 'string' || !/^[A-Za-z_][A-Za-z0-9_+.-]*(?:\/[A-Za-z0-9_+.-]+)*$/.test(timezone)) {
    throw new TypeError('Explicit named timezone required.');
  }
  return timezone;
}
export function instant(value, timezone) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/.test(value)) throw new TypeError('Explicit offset required.');
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new TypeError('Invalid instant.');
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone: namedTimezone(timezone),
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(p => [p.type, p.value]));
  const local = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
  if (local !== value.slice(0, 19)) throw new TypeError('Offset does not match timezone.');
  return date.getTime();
}
export function location(provider, locationId, timezone) {
  new Intl.DateTimeFormat('en', {timeZone: namedTimezone(timezone)}).format(0);
  return Object.freeze({provider: text(provider), locationId: text(locationId), timezone: text(timezone)});
}
export function room(locationValue, roomId) {
  const l = location(locationValue.provider, locationValue.locationId, locationValue.timezone);
  return Object.freeze({location: l, roomId: text(roomId)});
}
export function interval(start, end, timezone) {
  if (instant(start, timezone) >= instant(end, timezone)) throw new TypeError('Expected positive interval.');
  return Object.freeze({start, end, timezone});
}
export function bufferedInterval(value, setupMinutes = 0, cleanupMinutes = 0) {
  if (![setupMinutes, cleanupMinutes].every(n => Number.isSafeInteger(n) && n >= 0)) throw new TypeError('Expected nonnegative whole minutes.');
  const i = interval(value.start, value.end, value.timezone);
  return Object.freeze([instant(i.start, i.timezone) - setupMinutes * 60000,
    instant(i.end, i.timezone) + cleanupMinutes * 60000]);
}
export function withinWindow(value, window, setupMinutes = 0, cleanupMinutes = 0) {
  const [start, end] = bufferedInterval(value, setupMinutes, cleanupMinutes);
  const [opens, closes] = bufferedInterval(window);
  return opens <= start && end <= closes;
}
export function availabilityRequest(roomValue, intervalValue) {
  const r = room(roomValue.location, roomValue.roomId);
  const i = interval(intervalValue.start, intervalValue.end, intervalValue.timezone);
  if (r.location.timezone !== i.timezone) throw new TypeError('Use location timezone.');
  return Object.freeze({room: r, interval: i});
}
export function bookingRequest(roomValue, intervalValue, attemptId) {
  return Object.freeze({...availabilityRequest(roomValue, intervalValue), attemptId: text(attemptId)});
}
function copyBooking(request) { return bookingRequest(request.room, request.interval, request.attemptId); }
export function confirmationEvidence(request, bookingId, origin, reference, verified) {
  if (typeof verified !== 'boolean') throw new TypeError('Expected verification flag.');
  return Object.freeze({request: copyBooking(request), bookingId: text(bookingId),
    origin: text(origin), reference: text(reference), verified});
}
export function evidenceMatches(evidence, request, bookingId, expectedOrigin) {
  if (!evidence || evidence.verified !== true) return false;
  // Canonical factories remove key-order and aliasing differences; identity stays exact.
  return JSON.stringify(copyBooking(evidence.request)) === JSON.stringify(copyBooking(request)) &&
    evidence.bookingId === bookingId && evidence.origin === expectedOrigin;
}
export function operationResult(outcome, request, {slots = [], bookingId = null, evidence = null, expectedOrigin = null} = {}) {
  if (!OUTCOMES.includes(outcome)) throw new TypeError('Expected explicit outcome.');
  const r = Object.hasOwn(request, 'attemptId') ? copyBooking(request) : availabilityRequest(request.room, request.interval);
  const copied = slots.map(s => interval(s.start, s.end, s.timezone));
  if (copied.some(s => s.timezone !== r.interval.timezone || !withinWindow(s, r.interval)) ||
      (copied.length && outcome !== 'available')) throw new TypeError('Invalid slots.');
  const e = evidence === null ? null : confirmationEvidence(evidence.request, evidence.bookingId,
    evidence.origin, evidence.reference, evidence.verified);
  if (outcome === 'confirmed' && (!expectedOrigin || !evidenceMatches(e, r, bookingId, expectedOrigin))) throw new TypeError('Confirmation requires exact verified evidence.');
  return Object.freeze({outcome, request: r, slots: Object.freeze(copied), bookingId, evidence: e, expectedOrigin});
}
export function capabilities(operations = {}) {
  if (Object.keys(operations).some(k => !OPERATIONS.includes(k)) ||
      Object.values(operations).some(v => !SUPPORT.includes(v))) throw new TypeError('Invalid capability.');
  return Object.freeze(Object.fromEntries(OPERATIONS.map(k => [k, Object.hasOwn(operations, k) ? operations[k] : 'unsupported'])));
}
// Adapter shape: {capabilities, availability(request, dependencies), book(request, dependencies)}.
// dependencies: {transport, credentials, clock, contact, configuration, evidence} supplied by caller.
// Callbacks own deadlines, cancellation and cleanup. Never automatically replay uncertain writes.
