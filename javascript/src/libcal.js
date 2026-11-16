/** Read-only LibCal public-search mechanics; all provider routing is caller supplied. */
import {location, room, availabilityRequest, operationResult, capabilities, instant} from './index.js';

class Failure extends Error {
  constructor(detail, outcome = 'deferred') { super(detail); this.detail = detail; this.outcome = outcome; }
}
const fail = (detail, outcome) => { throw new Failure(detail, outcome); };
const positive = value => typeof value === 'string' && value === value.trim() && /^[1-9]\d*$/.test(value);
function pathAllowed(path) {
  return /^\/(?:r\/search|spaces|space\/[1-9]\d*|reserve\/spaces\/[a-zA-Z0-9_-]+)$/.test(path);
}
function checkedUrl(raw, origin) {
  const url = new URL(raw, origin);
  if (url.protocol !== 'https:' || url.username || url.password || url.hash ||
      (origin && url.origin !== origin) || !pathAllowed(url.pathname) ||
      [...url.searchParams.keys()].some(k => !['lid', 'gid', 'm', 'capacity', 'date', 'start', 'end'].includes(k))) {
    throw new TypeError('Expected configured HTTPS read-only LibCal URL.');
  }
  for (const key of ['lid', 'gid', 'capacity']) {
    for (const value of url.searchParams.getAll(key)) {
      if (!(key === 'capacity' ? /^(?:0|[1-9][0-9]*)$/.test(value) : positive(value))) {
        throw new TypeError('Expected complete decimal URL fields.');
      }
    }
  }
  return url;
}
function configuration(raw) {
  const c = {...raw, allowedOrigins: [...(raw?.allowedOrigins || [])]};
  if (c.provider !== 'libcal') return null;
  const url = checkedUrl(c.bookingUrl);
  if (!c.allowedOrigins.includes(url.origin) || !/^[a-z0-9-]+\.libcal\.com$/i.test(url.hostname) ||
      !positive(c.locationId) || !positive(c.groupId)) throw new TypeError('Explicit LibCal origin/location/group required.');
  // Provider kind selects mechanics; namespace supplies neutral tenant identity.
  const namespace = Object.hasOwn(c, 'namespace') ? c.namespace : c.provider;
  const l = location(namespace, c.locationId, c.timezone);
  return Object.freeze({...c, url: url.href, origin: url.origin, location: l});
}
function field(text, name) {
  const matches = [...text.matchAll(new RegExp(`(?:^|[,\\s])${name}\\s*:\\s*("[^"\\n]*"|'[^'\\n]*'|[^,\\r\\n]*)(?=\\s*(?:,|$))`, 'g'))];
  if (!matches.length) {
    if (new RegExp(`(?:^|[,\\s])${name}\\s*:`).test(text)) fail('unrecognized_markup');
    return '';
  }
  if (matches.length !== 1) fail('unrecognized_markup');
  const token = matches[0][1].trim();
  const quoted = /^(?:"([^"\n]*)"|'([^'\n]*)')$/.exec(token);
  if (quoted) {
    const value = quoted[1] ?? quoted[2];
    if (name !== 'title' && !value) fail('unrecognized_markup');
    return value;
  }
  if (!/^[0-9]+$/.test(token)) fail('unrecognized_markup');
  return token;
}
function clean(value) {
  return value.replace(/\\u([0-9a-f]{4})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16))).replace(/\\\//g, '/').trim();
}
function parseResources(html, c) {
  const blocks = [...html.matchAll(/resources\.push\(\s*\{([^{}]*)\}\s*\)/g)].map(m => m[1]);
  for (const array of html.matchAll(/\b(?:var|let|const)\s+resources\s*=\s*\[([\s\S]*?)\]\s*;/g)) {
    blocks.push(...[...array[1].matchAll(/\{([^{}]*)\}/g)].map(m => m[1]));
  }
  const resources = new Map();
  for (const block of blocks) {
    const eid = field(block, 'eid');
    const alias = field(block, 'id');
    const aliasId = alias.replace(/^eid_/, '');
    const lid = field(block, 'lid'), gid = field(block, 'gid');
    const id = eid || aliasId;
    const name = clean(field(block, 'title'));
    const capacity = field(block, 'capacity');
    if (!positive(id) || (eid && !positive(eid)) || (alias && !positive(aliasId)) ||
        !name || !positive(lid) || !positive(gid) ||
        (capacity && (capacity !== capacity.trim() || !/^(?:0|[1-9][0-9]*)$/.test(capacity) || !Number.isSafeInteger(Number(capacity))))) fail('unrecognized_markup');
    if ((eid && alias && eid !== aliasId) || lid !== c.locationId || gid !== c.groupId) fail('resource_identity_mismatch');
    const resource = Object.freeze({room: room(c.location, id), name,
      capacity: positive(capacity) && Number.isSafeInteger(Number(capacity)) ? Number(capacity) : null,
      groupId: c.groupId});
    if (resources.has(id) && JSON.stringify(resources.get(id)) !== JSON.stringify(resource)) fail('conflicting_resources');
    resources.set(id, resource);
  }
  return [...resources.values()];
}
function searchIds(html) {
  const start = html.indexOf('id="s-lc-eq-search-results"');
  const other = html.indexOf('id="s-lc-eq-search-other-results"', start);
  if (start < 0 || !html.includes('id="s-lc-search-filters"') || other < start) fail('unrecognized_markup');
  const exact = html.slice(start, other);
  const ids = new Set();
  for (const match of exact.matchAll(/(?:href="\/space\/([^"<>]*)"|name="eid"\s+value="([^"<>]*)")/g)) {
    const id = match[1] === undefined ? match[2] : match[1].split('?')[0];
    if (!positive(id)) fail('unrecognized_markup');
    ids.add(id);
  }
  // Empty markup alone does not prove an empty result; require the provider's explicit message.
  if (!ids.size && !/No (?:matches|spaces|rooms|results|availability)\b/i.test(exact)) fail('unrecognized_markup');
  return ids;
}
function searchUrl(c, request) {
  const {start, end, timezone} = request.interval;
  const a = instant(start, timezone), b = instant(end, timezone);
  if (start.slice(0, 10) !== end.slice(0, 10) || start.slice(17, 19) !== '00' || end.slice(17, 19) !== '00' ||
      start.slice(19) !== end.slice(19)) fail('unsupported_interval', 'unsupported');
  // Offset-free search cannot distinguish either occurrence of a folded wall time.
  for (const [value, ms] of [[start, a], [end, b]]) {
    const local = value.slice(0, 19);
    const format = new Intl.DateTimeFormat('sv-SE', {timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
    if ([-7200000, -3600000, 3600000, 7200000].some(delta => format.format(new Date(ms + delta)).replace(' ', 'T') === local)) {
      fail('unsupported_interval', 'unsupported');
    }
  }
  const configured = new URL(c.url);
  const url = new URL(configured.pathname.startsWith('/reserve/spaces/') ? configured.pathname : '/r/search', c.origin);
  for (const [key, value] of Object.entries({lid: c.locationId, gid: c.groupId, m: 't', capacity: '0',
    date: start.slice(0, 10), start: start.slice(11, 16), end: end.slice(11, 16)})) url.searchParams.set(key, value);
  return url;
}

export function createLibCalAdapter({fetch: fetchImpl, configuration: raw, timeoutMs = 5000, maxBytes = 524288, maxRooms = 20} = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('Injected fetch required.');
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000 ||
      !Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 2000000 ||
      !Number.isSafeInteger(maxRooms) || maxRooms < 1 || maxRooms > 20) throw new TypeError('Invalid bounds.');
  const c = configuration(raw);
  const support = capabilities(c ? {discovery: 'supported', availability: 'supported'} : {});

  async function bounded(work) {
    const controller = new AbortController();
    const readers = new Set();
    const bodies = new Set();
    let total = 0, calls = 0, timer;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => { controller.abort(); reject(new Failure('timeout')); }, timeoutMs);
    });
    async function get(rawUrl) {
      if (controller.signal.aborted) fail('timeout');
      if (++calls > maxRooms + 2) fail('request_limit');
      const url = checkedUrl(rawUrl, c.origin);
      const response = await fetchImpl(url.href, {method: 'GET', redirect: 'manual', credentials: 'omit',
        signal: controller.signal, headers: {accept: 'text/html,application/xhtml+xml'}});
      if (response.body) {
        if (controller.signal.aborted) Promise.resolve(response.body.cancel()).catch(() => {});
        else bodies.add(response.body);
      }
      if (controller.signal.aborted) fail('timeout');
      if (response.status === 401 || response.status === 403) fail('authentication_required', 'authentication_required');
      if (response.status >= 300 && response.status < 400 || response.redirected) fail('redirect_rejected');
      if (response.url && new URL(response.url).href !== url.href) fail('response_url_mismatch');
      if (!response.ok) fail('http_failure');
      if (!/^(?:text\/html|application\/xhtml\+xml)\b/i.test(response.headers.get('content-type') || '')) fail('content_type');
      const length = response.headers.get('content-length');
      if (length !== null && (!/^\d+$/.test(length) || Number(length) > maxBytes - total)) fail('response_too_large');
      const reader = response.body?.getReader();
      if (!reader) fail('unreadable_response');
      bodies.delete(response.body);
      readers.add(reader);
      const decoder = new TextDecoder('utf-8', {fatal: true});
      let html = '';
      try {
        while (true) {
          const {done, value} = await reader.read();
          if (controller.signal.aborted) fail('timeout');
          if (done) break;
          total += value.byteLength;
          if (total > maxBytes) fail('response_too_large');
          html += decoder.decode(value, {stream: true});
        }
        html += decoder.decode();
      } finally {
        readers.delete(reader);
        // Do not await cleanup: a hostile injected stream must not defeat the deadline.
        Promise.resolve(reader.cancel()).catch(() => {});
      }
      if (/<input\b[^>]*type\s*=\s*["']password["']/i.test(html)) fail('authentication_required', 'authentication_required');
      return html;
    }
    try { return await Promise.race([Promise.resolve().then(() => work(get)), deadline]); }
    finally {
      clearTimeout(timer);
      controller.abort();
      for (const reader of readers) Promise.resolve(reader.cancel()).catch(() => {});
      for (const body of bodies) Promise.resolve(body.cancel()).catch(() => {});
    }
  }
  function problem(error) {
    return error instanceof Failure ? error : new Failure('malformed_response_or_transport_failure');
  }
  return Object.freeze({
    capabilities: support,
    async discover(target) {
      const l = location(target.provider, target.locationId, target.timezone);
      const result = (outcome, resources = [], detail = '') => Object.freeze({outcome, location: l, resources: Object.freeze(resources), detail});
      if (!c || JSON.stringify(l) !== JSON.stringify(c.location)) return result('unsupported', [], 'unsupported_location');
      try {
        const resources = await bounded(async get => {
          const html = await get(c.url);
          const direct = parseResources(html, c);
          const requestedPath = new URL(c.url).pathname;
          if (requestedPath.startsWith('/space/')) {
            if (direct.length !== 1 || direct[0].room.roomId !== requestedPath.split('/').pop()) fail('resource_identity_mismatch');
            return direct;
          }
          if (direct.length) {
            if (direct.length > maxRooms) fail('room_limit');
            return direct;
          }
          const form = html.match(/<form\b[^>]*id="s-lc-by-space-search-filters"[^>]*>([\s\S]*?)<\/form>/i)?.[1];
          const lid = form?.match(/<input\b[^>]*name="lid"[^>]*value="(\d+)"/i)?.[1];
          const select = form?.match(/<select\b[^>]*name="gid"[^>]*>([\s\S]*?)<\/select>/i)?.[1] || '';
          if ([...select.matchAll(/<option\b[^>]*value="([^"]*)"/gi)].some(m => !/^(?:0|[1-9][0-9]*)$/.test(m[1]))) fail('unrecognized_markup');
          const groups = [...select.matchAll(/<option\b[^>]*value="([1-9]\d*)"[^>]*selected\b/gi)].map(m => m[1]);
          if (!html.includes('searchFilters:') || lid !== c.locationId || groups.length !== 1 || groups[0] !== c.groupId) fail('unrecognized_markup');
          const url = new URL(c.url);
          url.searchParams.set('m', 's'); url.searchParams.set('gid', c.groupId);
          const listing = await get(url.href);
          const paths = [...new Set([...listing.matchAll(/href="(\/space\/[^"<>]*)"/g)].map(m => m[1]))];
          if (paths.some(path => !/^\/space\/[1-9][0-9]*$/.test(path))) fail('unrecognized_markup');
          if (!paths.length) fail('unrecognized_markup');
          if (paths.length > maxRooms) fail('room_limit');
          const found = new Map();
          for (const path of paths) {
            const parsed = parseResources(await get(path), c);
            if (parsed.length !== 1 || parsed[0].room.roomId !== path.split('/').pop()) fail('resource_identity_mismatch');
            found.set(parsed[0].room.roomId, parsed[0]);
          }
          return [...found.values()];
        });
        return result('available', resources);
      } catch (error) { const p = problem(error); return result(p.outcome, [], p.detail); }
    },
    async availability(input) {
      const request = availabilityRequest(input.room, input.interval);
      const result = (outcome, detail = '') => Object.freeze({...operationResult(outcome, request,
        {slots: outcome === 'available' ? [request.interval] : []}), detail});
      if (!c || JSON.stringify(request.room.location) !== JSON.stringify(c.location) || !positive(request.room.roomId)) {
        return result('unsupported', 'unsupported_location_or_room');
      }
      try {
        const url = searchUrl(c, request);
        const ids = await bounded(async get => searchIds(await get(url.href)));
        return result(ids.has(request.room.roomId) ? 'available' : 'unavailable');
      } catch (error) { const p = problem(error); return result(p.outcome, p.detail); }
    }
  });
}
