/** Executed only against the packed and installed npm artifact. All inputs synthetic. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';
import {createLibCalAdapter} from '@mathist/library-room-booking/libcal';
import {availabilityRequest, capabilities, operationResult} from '@mathist/library-room-booking';
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).cases;
const base = cases[0];
const page = exact => `<form id="s-lc-search-filters"></form><div id="s-lc-eq-search-results">${exact}</div><div id="s-lc-eq-search-other-results"><a href="/space/999">Other time</a></div>`;
const resource = (row, extra = '') => `resources.push({eid:${row.room.roomId},title:"Synthetic\\u0020Room",lid:${row.configuration.locationId},gid:${row.configuration.groupId},capacity:4${extra}});`;
const response = html => new Response(html, {headers: {'content-type': 'text/html'}});
const adapter = (fetch, options = {}) => createLibCalAdapter({fetch, configuration: base.configuration, ...options});
const request = row => availabilityRequest(row.room, row.interval);

test('multiple configured LibCal origins: exact shared identities, result and safe search parameters', async () => {
  for (const row of cases) {
    const calls = [];
    const provider = createLibCalAdapter({configuration: row.configuration, fetch: async (url, options) => {
      calls.push({url: new URL(url), options});
      return response(page(`<a href="/space/${row.room.roomId}?x=1">Synthetic</a>`));
    }});
    const result = await provider.availability(request(row));
    assert.deepEqual(result, {...operationResult(row.outcome, request(row), {slots: [row.interval]}), detail: ''});
    assert.equal(provider.capabilities.booking, 'unsupported');
    assert.equal(provider.book, undefined);
    assert.equal(calls.length, 1);
    const {url, options} = calls[0];
    assert.equal(url.origin, row.configuration.allowedOrigins[0]);
    assert.equal(url.pathname, row === base ? '/reserve/spaces/synthetic-a' : '/r/search');
    assert.equal(url.searchParams.get('lid'), row.configuration.locationId);
    assert.equal(url.searchParams.get('gid'), row.configuration.groupId);
    assert.equal(url.searchParams.get('date'), row.interval.start.slice(0, 10));
    assert.equal(url.searchParams.get('start'), row.interval.start.slice(11, 16));
    assert.equal(url.searchParams.get('end'), row.interval.end.slice(11, 16));
    assert.equal(options.method, 'GET'); assert.equal(options.redirect, 'manual');
    assert.equal(options.credentials, 'omit'); assert.equal(options.body, undefined);
  }
});
test('inline push and array discovery retain neutral room identity without category policy', async () => {
  for (const row of cases) {
    const html = row === base ? resource(row) : resource(row).replace('resources.push({', 'const resources = [{').replace('});', '}];');
    const provider = createLibCalAdapter({configuration: row.configuration, fetch: async () => response(html)});
    const result = await provider.discover(row.room.location);
    assert.equal(result.outcome, 'available');
    assert.deepEqual(result.resources, [{room: row.room, name: 'Synthetic Room', capacity: 4, groupId: row.configuration.groupId}]);
    assert.equal(Object.hasOwn(result.resources[0], 'bookingCategory'), false);
    assert.throws(() => {result.resources[0].room.roomId = 'changed';});
  }
});
const form = `<form id="s-lc-by-space-search-filters"><input name="lid" value="41"><select name="gid"><option value="0" selected>All</option><option value="51" selected>Rooms</option></select></form><script>searchFilters: {}</script>`;
test('bounded search/detail discovery, exact location/group and detail identity', async () => {
  let calls = [];
  const provider = adapter(async (url, options) => {
    calls.push({url, options});
    const u = new URL(url);
    return response(u.pathname === '/space/61' ? resource(base) : u.searchParams.get('m') === 's' ? '<a href="/space/61">Room</a>' : form);
  });
  assert.deepEqual((await provider.discover(base.room.location)).resources[0].room, base.room);
  assert.equal(calls.length, 3);
  assert.ok(calls.every(c => c.options.method === 'GET' && c.options.redirect === 'manual'));
  const mismatch = adapter(async url => response(new URL(url).pathname === '/space/61' ? resource(base).replace('lid:41', 'lid:99') : new URL(url).search ? '<a href="/space/61">Room</a>' : form));
  assert.equal((await mismatch.discover(base.room.location)).detail, 'resource_identity_mismatch');
});
test('alternate provider capabilities and unsupported LibCal configuration perform no transport', async () => {
  let calls = 0;
  const other = {capabilities: capabilities({availability: 'supported'}), availability: async req => operationResult('available', req, {slots: [req.interval]})};
  assert.equal((await other.availability(request(base))).outcome, 'available');
  assert.equal(other.capabilities.discovery, 'unsupported');
  const provider = adapter(async () => {calls++;}, {configuration: {provider: 'fake'}});
  assert.equal((await provider.availability(request(base))).outcome, 'unsupported');
  assert.equal((await provider.discover(base.room.location)).outcome, 'unsupported');
  const configured = adapter(async () => {calls++;});
  assert.equal((await configured.availability({...request(base), room: {...base.room, roomId: 'bad'}})).outcome, 'unsupported');
  assert.equal(calls, 0);
});
test('coverage uses exact IDs only and excludes other-time suggestions and name-only matches', async () => {
  for (const exact of ['No matches for this time', '<a href="/space/999">Synthetic Room</a>']) {
    assert.equal((await adapter(async () => response(page(exact))).availability(request(base))).outcome, 'unavailable');
  }
  assert.equal((await adapter(async () => response(page('<input name="eid" value="61">'))).availability(request(base))).outcome, 'available');
  const suggested = {...request(base), room: {...base.room, roomId: '999'}};
  assert.equal((await adapter(async () => response(page('<a href="/space/61">Exact</a>'))).availability(suggested)).outcome, 'unavailable');
});
test('unfamiliar, empty, partial and malformed markup stay explicitly unrecognized', async () => {
  for (const html of ['<html>challenge</html>', page(''), '<div id="s-lc-eq-search-results"><a href="/space/61">x</a>', page('<a href="/space/610abc">x</a>')]) {
    const result = await adapter(async () => response(html)).availability(request(base));
    assert.equal(result.outcome, 'deferred'); assert.equal(result.detail, 'unrecognized_markup'); assert.deepEqual(result.slots, []);
  }
  const result = await adapter(async () => response('resources.push({eid:61});')).discover(base.room.location);
  assert.equal(result.detail, 'unrecognized_markup');
});
test('DST folds, transitions, midnight and subminute requests fail explicitly without fetching', async () => {
  let calls = 0;
  const provider = adapter(async () => {calls++;});
  for (const [start, end] of [
    ['2026-11-01T01:30:00-06:00', '2026-11-01T01:30:00-07:00'],
    ['2026-11-01T01:10:00-07:00', '2026-11-01T01:40:00-07:00'],
    ['2026-03-08T01:30:00-07:00', '2026-03-08T03:30:00-06:00'],
    ['2026-10-14T23:00:00-06:00', '2026-10-15T01:00:00-06:00'],
    ['2026-10-14T18:30:01-06:00', '2026-10-14T19:00:00-06:00']]) {
    const result = await provider.availability({...request(base), interval: {start, end, timezone: 'America/Denver'}});
    assert.equal(result.outcome, 'unsupported'); assert.equal(result.detail, 'unsupported_interval');
  }
  assert.equal(calls, 0);
  await assert.rejects(() => provider.availability({...request(base), interval: {start:'2026-03-08T02:30:00-07:00',end:'2026-03-08T04:00:00-06:00',timezone:'America/Denver'}}));
  const winter = {...request(base), interval:{start:'2026-11-02T12:00:00-07:00',end:'2026-11-02T13:00:00-07:00',timezone:'America/Denver'}};
  assert.equal((await adapter(async () => response(page('<a href="/space/61">x</a>'))).availability(winter)).outcome, 'available');
});
test('auth, redirect, MIME, HTTP and response URL failures; single attempt only', async () => {
  for (const [make, outcome, detail] of [
    [() => new Response('', {status:401}), 'authentication_required', 'authentication_required'],
    [() => new Response('', {status:403}), 'authentication_required', 'authentication_required'],
    [() => response('<input type="password">'), 'authentication_required', 'authentication_required'],
    [() => new Response('', {status:302,headers:{location:'https://evil.invalid/'}}), 'deferred', 'redirect_rejected'],
    [() => new Response('', {status:500}), 'deferred', 'http_failure'],
    [() => new Response('{}',{headers:{'content-type':'application/json'}}), 'deferred', 'content_type'],
    [() => {const r=response('');Object.defineProperty(r,'url',{value:'https://evil.invalid/'});return r;},'deferred','response_url_mismatch'],
    [() => {throw new Error('private provider secret');}, 'deferred','malformed_response_or_transport_failure']]) {
    let calls=0;
    const provider=adapter(async () => {calls++;return make();});
    const result=await provider.availability(request(base));
    assert.equal(result.outcome,outcome);assert.equal(result.detail,detail);assert.equal(calls,1);
    assert.equal((await provider.discover(base.room.location)).detail,detail);
  }
});
test('byte bounds apply while streaming, to content length and across discovery responses', async () => {
  let cancelled=false;
  const streamed=adapter(async () => new Response(new ReadableStream({pull(c){c.enqueue(new TextEncoder().encode('xxxxxxxxxx'));},cancel(){cancelled=true;}}),{headers:{'content-type':'text/html'}}),{maxBytes:15});
  assert.equal((await streamed.availability(request(base))).detail,'response_too_large');assert.equal(cancelled,true);
  const length=adapter(async () => new Response('',{headers:{'content-type':'text/html','content-length':'100'}}),{maxBytes:15});
  assert.equal((await length.availability(request(base))).detail,'response_too_large');
  let calls=0;
  const aggregate=adapter(async () => response(++calls===1?form:'<a href="/space/61">Room</a>'),{maxBytes:new TextEncoder().encode(form).length+1});
  assert.equal((await aggregate.discover(base.room.location)).detail,'response_too_large');assert.equal(calls,2);
});
test('deadlines bound fetch and body stalls even if injected fetch ignores abort', async () => {
  let signal;
  const never=adapter(async (_,options) => {signal=options.signal;return new Promise(()=>{});},{timeoutMs:10});
  assert.equal((await never.availability(request(base))).detail,'timeout');assert.equal(signal.aborted,true);
  let cancelled=false;
  const body=adapter(async () => new Response(new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled=true;}}),{headers:{'content-type':'text/html'}}),{timeoutMs:10});
  assert.equal((await body.discover(base.room.location)).detail,'timeout');assert.equal(cancelled,true);
});
test('room discovery bounds and malformed UTF-8',async()=>{
  const tooMany=adapter(async url=>response(new URL(url).search?' <a href="/space/61">A</a><a href="/space/62">B</a>':form),{maxRooms:1});
  assert.equal((await tooMany.discover(base.room.location)).detail,'room_limit');
  const invalid=adapter(async()=>new Response(new Uint8Array([255]),{headers:{'content-type':'text/html'}}));
  assert.equal((await invalid.availability(request(base))).detail,'malformed_response_or_transport_failure');
});
test('configuration rejects unsafe routing, hold endpoints and unbounded options; snapshots inputs',async()=>{
  for(const bookingUrl of ['http://alpha.libcal.com/spaces','https://evil.invalid/spaces','https://u:p@alpha.libcal.com/spaces',
    'https://alpha.libcal.com/spaces/availability/booking/add','https://alpha.libcal.com/r/search?next=https://evil.invalid/',
    'https://alpha.libcal.com//evil.invalid/','https://alpha.libcal.com/spaces#fragment']){
    assert.throws(()=>adapter(async()=>{}, {configuration:{...base.configuration,bookingUrl}}));
  }
  for(const options of [{timeoutMs:0},{timeoutMs:30001},{maxBytes:0},{maxBytes:2000001},{maxRooms:21}]) assert.throws(()=>adapter(async()=>{},options));
  assert.throws(()=>createLibCalAdapter({configuration:base.configuration}));
  const configuration=structuredClone(base.configuration);
  const provider=adapter(async()=>response(page('<a href="/space/61">x</a>')),{configuration});
  configuration.locationId='999';configuration.allowedOrigins.length=0;
  assert.equal((await provider.availability(request(base))).outcome,'available');
});

test('P2 namespaces isolate colliding tenant IDs and preserve exact request identity', async () => {
  let calls = 0;
  const namespaced = namespace => ({...base.configuration, namespace});
  const alpha = {...base.room, location: {...base.room.location, provider: 'libcal-alpha'}};
  const beta = {...base.room, location: {...base.room.location, provider: 'libcal-beta'}};
  const provider = adapter(async () => {calls++; return response(page('<a href="/space/61">Room</a>'));},
    {configuration: {...namespaced('libcal-beta'), bookingUrl: 'https://beta.libcal.com/spaces', allowedOrigins: ['https://beta.libcal.com']}});
  const foreign = availabilityRequest(alpha, base.interval);
  const denied = await provider.availability(foreign);
  assert.equal(denied.outcome, 'unsupported');
  assert.deepEqual(denied.request, foreign);
  assert.equal((await provider.discover(alpha.location)).outcome, 'unsupported');
  assert.equal(calls, 0);
  const own = availabilityRequest(beta, base.interval);
  assert.deepEqual(await provider.availability(own), {...operationResult('available', own, {slots: [base.interval]}), detail: ''});
  assert.equal(calls, 1);
  const discovery = adapter(async () => response(resource(base)), {configuration: namespaced('libcal-alpha')});
  assert.deepEqual((await discovery.discover(alpha.location)).resources[0].room, alpha);
  for (const namespace of ['', null, 42, ' padded ']) assert.throws(() => adapter(async () => {}, {configuration: namespaced(namespace)}));
});

test('P2 direct room page requires exactly the requested room, including array layouts', async () => {
  for (const array of [false, true]) {
    for (const [ids, outcome] of [[[61], 'available'], [[62], 'deferred'], [[61, 62], 'deferred']]) {
      let html = ids.map(id => resource({...base, room: {...base.room, roomId: String(id)}})).join('');
      if (array) html = `const resources = [${ids.map(id => `{eid:${id},title:"Room",lid:41,gid:51}`).join(',')}];`;
      const result = await adapter(async () => response(html), {configuration: {...base.configuration, bookingUrl: 'https://alpha.libcal.com/space/61'}}).discover(base.room.location);
      assert.equal(result.outcome, outcome, `${array}: ${ids}`);
      if (outcome === 'deferred') {assert.equal(result.detail, 'resource_identity_mismatch'); assert.deepEqual(result.resources, []);}
      else assert.deepEqual(result.resources[0].room, base.room);
    }
  }
});

test('P2 numeric resource fields reject entire malformed tokens without identity fallback', async t => {
  for (const field of ['eid', 'id', 'lid', 'gid', 'capacity']) {
    for (const token of ['61.5', '61e2', '61oops', '61+2', '0x3d', '-61', '+61', 'NaN', 'Infinity', '"61.5"', "'61e2'"]) {
      await t.test(`${field}=${token}`, async () => {
        const fields = {eid: '61', title: '"Room"', lid: '41', gid: '51', capacity: '4'};
        if (field === 'id') fields.id = token; else fields[field] = token;
        const html = `resources.push({${Object.entries(fields).map(([key, value]) => `${key}:${value}`).join(',')}});`;
        const result = await adapter(async () => response(html)).discover(base.room.location);
        assert.equal(result.outcome, 'deferred'); assert.equal(result.detail, 'unrecognized_markup'); assert.deepEqual(result.resources, []);
      });
    }
  }
  for (const html of ['resources.push({id:"eid_61",title:"Room",lid:"41",gid:\'51\',capacity:4});', resource(base)]) {
    assert.deepEqual((await adapter(async () => response(html)).discover(base.room.location)).resources[0].room, base.room);
  }
});

test('P2 numeric boundaries cover configuration, requests, search, forms and listing fields', async () => {
  for (const token of ['61.5', '61e2', '61oops', '061', '0', '-61']) {
    for (const field of ['locationId', 'groupId']) {
      assert.throws(() => adapter(async () => {}, {configuration: {...base.configuration, [field]: token}}));
    }
    for (const key of ['lid', 'gid', 'capacity']) {
      assert.throws(() => adapter(async () => {}, {configuration: {...base.configuration, bookingUrl: `https://alpha.libcal.com/spaces?${key}=${token === '0' && key === 'capacity' ? '0oops' : token}`}}));
    }
    let calls = 0;
    const result = await adapter(async () => {calls++;}).availability({...request(base), room: {...base.room, roomId: token}});
    assert.equal(result.outcome, 'unsupported'); assert.equal(calls, 0); assert.equal(result.request.room.roomId, token);
    for (const exact of [`<a href="/space/61">Valid</a><a href="/space/${token}">Malformed</a>`, `<input name="eid" value="${token}">No matches`]) {
      const result = await adapter(async () => response(page(exact))).availability(request(base));
      assert.equal(result.outcome, 'deferred'); assert.equal(result.detail, 'unrecognized_markup'); assert.deepEqual(result.slots, []);
    }
    for (const field of ['lid', 'gid']) {
      const html = form.replace(field === 'lid' ? 'value="41"' : 'value="51"', `value="${token}"`);
      assert.equal((await adapter(async () => response(html)).discover(base.room.location)).detail, 'unrecognized_markup');
    }
    let fetches = 0;
    const listing = adapter(async () => response(++fetches === 1 ? form : `<a href="/space/61">Valid</a><a href="/space/${token}">Malformed</a>`));
    assert.equal((await listing.discover(base.room.location)).detail, 'unrecognized_markup'); assert.equal(fetches, 2);
  }
});


test('P2 strict tokens preserve quoted titles and valid aliases, reject empty/conflicting aliases', async () => {
  const html = 'resources.push({eid:61,id:"eid_61",title:"Room, East",lid:41,gid:51,capacity:0});';
  const result = await adapter(async () => response(html)).discover(base.room.location);
  assert.equal(result.outcome, 'available'); assert.equal(result.resources[0].name, 'Room, East'); assert.equal(result.resources[0].capacity, null);
  for (const fields of ['eid:"",id:"eid_61"', 'eid:61,id:""', 'eid:61,id:"eid_62"']) {
    const result = await adapter(async () => response(`resources.push({${fields},title:"Room",lid:41,gid:51});`)).discover(base.room.location);
    assert.equal(result.outcome, 'deferred'); assert.deepEqual(result.resources, []);
  }
});
