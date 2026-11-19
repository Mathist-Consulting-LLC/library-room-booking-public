// Read-only synthetic LibCal discovery. No network or credentials.
import assert from 'node:assert/strict';
import {location, interval, availabilityRequest} from '@mathist/library-room-booking';
import {createLibCalAdapter} from '@mathist/library-room-booking/libcal';
let calls = 0;
const adapter = createLibCalAdapter({
  configuration: {provider: 'libcal', namespace: 'synthetic-library',
    bookingUrl: 'https://synthetic.libcal.com/spaces?lid=10&gid=20',
    allowedOrigins: ['https://synthetic.libcal.com'], locationId: '10', groupId: '20', timezone: 'America/Denver'},
  fetch: async (url, options) => {
    calls++;
    assert.equal(options.method, 'GET');
    assert.equal(options.redirect, 'manual');
    const markup = new URL(url).pathname === '/r/search'
      ? '<div id="s-lc-search-filters"></div><div id="s-lc-eq-search-results"><a href="/space/30">Study One</a></div><div id="s-lc-eq-search-other-results"></div>'
      : 'var resources = [{eid:30,gid:20,lid:10,capacity:6,title:"Study One"}];';
    return new Response(markup,
      {status: 200, headers: {'content-type': 'text/html'}});
  }
});
const found = await adapter.discover(location('synthetic-library', '10', 'America/Denver'));
assert.equal(found.outcome, 'available');
assert.equal(found.resources[0].room.roomId, '30');
console.log(`room=30; outcome=${found.outcome}; calls=${calls}`);
const request = availabilityRequest(found.resources[0].room,
  interval('2026-12-01T18:00:00-07:00', '2026-12-01T19:00:00-07:00', 'America/Denver'));
const result = await adapter.availability(request);
assert.equal(result.outcome, 'available');
console.log(`availability=${result.outcome}; calls=${calls}`);
assert.equal(adapter.capabilities.booking, 'unsupported');
assert.equal(typeof adapter.book, 'undefined');
console.log('booking=unsupported; no booking attempted');
