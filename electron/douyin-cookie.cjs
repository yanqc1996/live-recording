const COOKIE_NAME_PATTERN = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
const COOKIE_ATTRIBUTE_NAMES = new Set([
  'domain',
  'expires',
  'httponly',
  'max-age',
  'partitioned',
  'path',
  'samesite',
  'secure'
]);
const LOGIN_COOKIE_NAMES = new Set(['LOGIN_STATUS', 'sessionid', 'sessionid_ss', 'sid_guard']);
const DOUYIN_DOMAIN_METADATA_PATTERN = /^\.?(?:www\.)?douyin\.com$/i;

function parseCookieHeader(input) {
  if (typeof input !== 'string') throw new Error('Cookie 内容格式不正确');
  let raw = input.trim();
  if (!raw) throw new Error('请粘贴 Cookie');
  if (raw.length > 65536) throw new Error('Cookie 内容过长');
  raw = raw.replace(/^cookie\s*:\s*/i, '');
  if (/[\0\r\n]/.test(raw)) throw new Error('Cookie 中不能包含换行或控制字符');

  const cookies = new Map();
  for (const part of raw.split(';')) {
    const item = part.trim();
    if (!item) continue;
    const separator = item.indexOf('=');
    if (separator < 0 && COOKIE_ATTRIBUTE_NAMES.has(item.toLowerCase())) continue;
    if (separator < 0 && DOUYIN_DOMAIN_METADATA_PATTERN.test(item)) continue;
    if (separator <= 0) throw new Error(`无法识别 Cookie 片段：${item.slice(0, 32)}`);
    const name = item.slice(0, separator).trim();
    const value = item.slice(separator + 1).trim();
    if (!COOKIE_NAME_PATTERN.test(name)) throw new Error(`Cookie 名称不合法：${name.slice(0, 32)}`);
    if (COOKIE_ATTRIBUTE_NAMES.has(name.toLowerCase())) continue;
    if (!value) continue;
    cookies.set(name, value);
  }

  const result = [...cookies].map(([name, value]) => ({ name, value }));
  if (!result.length) throw new Error('没有找到有效的 Cookie');
  if (!result.some(({ name, value }) => LOGIN_COOKIE_NAMES.has(name) && value !== '0')) {
    throw new Error('未找到抖音登录凭证，请确认复制的是登录后的完整 Cookie');
  }
  return result;
}

module.exports = { LOGIN_COOKIE_NAMES, parseCookieHeader };
