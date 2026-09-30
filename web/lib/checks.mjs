export const platforms = {
  github: 'https://api.github.com/users/{n}',
  instagram: 'https://www.instagram.com/{n}/',
  x: 'https://x.com/{n}',
  youtube: 'https://www.youtube.com/@{n}',
  linkedin: 'https://www.linkedin.com/in/{n}',
  reddit: 'https://www.reddit.com/user/{n}/',
  threads: 'https://www.threads.net/@{n}',
  twitch: 'https://www.twitch.tv/{n}',
  pinterest: 'https://www.pinterest.com/{n}/',
  snapchat: 'https://www.snapchat.com/add/{n}',
  bluesky: 'https://bsky.app/profile/{n}',
  mastodon: '',
  telegram: 'https://t.me/{n}',
  producthunt: 'https://www.producthunt.com/@{n}',
  substack: 'https://{n}.substack.com/',
  medium: 'https://medium.com/@{n}',
  devto: 'https://dev.to/{n}',
  npm: 'https://registry.npmjs.org/{n}',
  pypi: 'https://pypi.org/pypi/{n}/json',
  dockerhub: 'https://hub.docker.com/v2/users/{n}/',
};
export const tlds = ['.com', '.ai', '.io', '.dev', '.co'];

export function parseName(input) {
  const name = input.trim().replace(/^@/, '');
  if (!/^[a-zA-Z0-9](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9])?$/.test(name)) {
    throw new Error('Enter a name of 1-63 letters, numbers, hyphens or underscores. We will not silently change it.');
  }
  return name.toLowerCase();
}

async function request(url, fetcher) {
  // Keep the deadline through body parsing, not just response headers.
  const controller = new AbortController();
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => { controller.abort(); reject(new Error('timeout')); }, 12000);
  });
  const read = async () => {
    const response = await fetcher(url, { signal: controller.signal, redirect: 'error', headers: { Accept: 'application/json' } });
    let data, empty = false;
    if (typeof response.text === 'function') {
      const body = await response.text();
      empty = body.trim() === '';
      data = empty ? null : JSON.parse(body);
    } else {
      data = await response.json();
    }
    return { status: response.status, data, empty };
  };
  try { return await Promise.race([read(), timeout]); }
  finally { clearTimeout(timer); }
}

export async function checkDomain(name, tld, fetcher = fetch) {
  const value = name + tld;
  const result = { platform: `domain:${tld}`, label: value, status: 'unknown', detail: 'No verified registration record; ask a registrar about claimability.', url: `https://rdap.org/domain/${encodeURIComponent(value)}` };
  if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(name)) {
    return { ...result, detail: 'This name is not a valid DNS label; underscores are not allowed.' };
  }
  try {
    const bootstrap = await request('https://data.iana.org/rdap/dns.json', fetcher);
    if (bootstrap.status !== 200) return { ...result, detail: 'IANA RDAP bootstrap unavailable.' };
    const registry = bootstrap.data;
    const service = registry?.services?.find(item => Array.isArray(item) && item.length === 2 && Array.isArray(item[0]) && item[0].includes(tld.slice(1)));
    const endpoint = Array.isArray(service?.[1]) ? service[1].find(value => { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash; } catch { return false; } }) : undefined;
    if (!endpoint) return { ...result, detail: 'No HTTPS registry RDAP service for this TLD. Use a registrar.' };
    result.url = endpoint.replace(/\/$/, '') + '/domain/' + encodeURIComponent(value);
    const r = await request(result.url, fetcher);
    if (r.status === 404) {
      const data = r.data;
      if (r.empty || (data && data.errorCode === 404)) return { ...result, status: 'not_registered', detail: 'Registry reports no record. Reserved, premium or policy restrictions may prevent registration; confirm with a registrar.' };
    }
    if (r.status !== 200) return { ...result, detail: `RDAP HTTP ${r.status}. Missing data does not prove a domain can be registered.` };
    const data = r.data;
    if (data && data.objectClassName === 'domain' && !data.errorCode && !data.error && typeof data.ldhName === 'string' && data.ldhName.toLowerCase().replace(/\.$/, '') === value) {
      return { ...result, status: 'taken', detail: 'Matching RDAP registration record. A registration is not an offer for sale.' };
    }
    return { ...result, detail: 'Source did not return a matching domain registration record.' };
  } catch { return { ...result, detail: 'Registration could not be verified: timeout, redirect, CORS, malformed data or source failure. Use the CLI.' }; }
}

export async function checkProfile(platform, name, fetcher = fetch) {
  const result = { platform, label: platform, status: 'unknown', detail: 'Public pages cannot prove account identity or claimability. Check the platform directly.', url: platforms[platform]?.replace('{n}', encodeURIComponent(name)) };
  if (!['github', 'npm', 'pypi', 'dockerhub'].includes(platform)) return result;
  try {
    const r = await request(result.url, fetcher);
    if (r.status !== 200) return { ...result, detail: `API HTTP ${r.status}. Missing records can mean deleted, restricted or reserved names.` };
    const data = r.data;
    if (!data || typeof data !== 'object' || data.error || data.errorCode) return { ...result, detail: 'Source returned an error or invalid identity record.' };
    let matches = false;
    if (platform === 'github') matches = data && Number.isInteger(data.id) && data.id > 0 && typeof data.login === 'string' && data.login.toLowerCase() === name;
    if (platform === 'npm') matches = data && data.name === name && data.versions && typeof data.versions === 'object' && !Array.isArray(data.versions);
    if (platform === 'pypi') matches = data && data.info && typeof data.info.name === 'string' && data.info.name.toLowerCase().replace(/[-_.]+/g, '-') === name.replace(/[-_.]+/g, '-');
    if (platform === 'dockerhub') matches = data && data.id && typeof data.username === 'string' && data.username.toLowerCase() === name;
    return matches ? { ...result, status: 'taken', detail: 'Matching public API identity record.' } : { ...result, detail: 'Source did not return a matching identity record.' };
  } catch { return { ...result, detail: 'Identity could not be verified: timeout, redirect, CORS, malformed data or source failure. Use the CLI.' }; }
}
