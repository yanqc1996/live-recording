const assert = require('node:assert/strict');
const test = require('node:test');

const { parseCookieHeader } = require('../electron/douyin-cookie.cjs');

test('parses a copied Cookie request header', () => {
  assert.deepEqual(
    parseCookieHeader('Cookie: ttwid=abc=123; sessionid_ss=login-token; LOGIN_STATUS=1'),
    [
      { name: 'ttwid', value: 'abc=123' },
      { name: 'sessionid_ss', value: 'login-token' },
      { name: 'LOGIN_STATUS', value: '1' }
    ]
  );
});

test('ignores Set-Cookie attributes and keeps the last duplicate', () => {
  assert.deepEqual(
    parseCookieHeader('sessionid=old; Path=/; Secure; HttpOnly; sessionid=new'),
    [{ name: 'sessionid', value: 'new' }]
  );
});

test('ignores a Douyin domain marker inserted by cookie export tools', () => {
  assert.deepEqual(
    parseCookieHeader('ttwid=value; sessionid_ss=login-token; douyin.com; odin_tt=value'),
    [
      { name: 'ttwid', value: 'value' },
      { name: 'sessionid_ss', value: 'login-token' },
      { name: 'odin_tt', value: 'value' }
    ]
  );
});

test('rejects content without a Douyin login cookie', () => {
  assert.throws(
    () => parseCookieHeader('ttwid=anonymous; msToken=value'),
    /未找到抖音登录凭证/
  );
});

test('rejects multiline content', () => {
  assert.throws(
    () => parseCookieHeader('sessionid=value\nanother=value'),
    /不能包含换行/
  );
});
