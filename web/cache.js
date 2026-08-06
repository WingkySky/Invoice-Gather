/* ======================================================== 票归集 · 缓存契约（CacheStore）
 * 命名空间 + 内存 / sessionStorage / localStorage 三级回退。
 *   key 格式 : ih:<ns>:<fingerprint>   fingerprint = 筛选条件稳定哈希
 *   value    : { v: dataVersion, ts: 拉取时刻ms, data: payload }
 * 回退链：内存 Map（最热）→ sessionStorage（按 tab 隔离的主缓存）→ 网络。
 * 所有页面必须经本模块读写缓存，禁止自管 sessionStorage。
 * 跨 tab 失效：post 成功后写 localStorage['ih:invalidations'] 并经 storage 事件广播。
 */
(function (global) {
  'use strict';

  var NS = {
    INVOICES: 'invoices',
    COMPANIES: 'companies',
    ACCOUNTS: 'accounts',
    STATS: 'stats'
  };
  var MANIFEST_KEY = 'ih:manifest';        // {ns: [keys]} 轻量清单（localStorage）
  var INVALIDATIONS_KEY = 'ih:invalidations'; // 跨 tab 失效信号（localStorage）
  var MEM = new Map();                     // 内存层：ns|key -> entry

  // ---- 稳定序列化（键顺序无关） ----
  function stableStringify(o) {
    if (o === null || typeof o !== 'object') return JSON.stringify(o);
    if (Array.isArray(o)) return '[' + o.map(stableStringify).join(',') + ']';
    var keys = Object.keys(o).sort();
    return '{' + keys.map(function (k) {
      return JSON.stringify(k) + ':' + stableStringify(o[k]);
    }).join(',') + '}';
  }
  function fp(obj) { return stableStringify(obj || {}); }
  function storageKey(ns, key) { return 'ih:' + ns + ':' + key; }

  // ---- manifest 读写（localStorage，仅存轻量键清单） ----
  function _readManifest() {
    try { return JSON.parse(localStorage.getItem(MANIFEST_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function _writeManifest(m) {
    try { localStorage.setItem(MANIFEST_KEY, JSON.stringify(m)); } catch (e) {}
  }
  function _addManifest(ns, key) {
    var m = _readManifest();
    m[ns] = m[ns] || [];
    if (m[ns].indexOf(key) === -1) m[ns].push(key);
    _writeManifest(m);
  }
  function _removeManifest(ns, key) {
    var m = _readManifest();
    if (m[ns]) { m[ns] = m[ns].filter(function (k) { return k !== key; }); _writeManifest(m); }
  }
  function _clearManifest(ns) {
    var m = _readManifest();
    delete m[ns];
    _writeManifest(m);
  }
  function _manifestKeys(ns) {
    var m = _readManifest();
    return (m[ns] || []).slice();
  }

  // ---- 三级读写 ----
  function set(ns, key, data, version) {
    var entry = { v: version | 0, ts: Date.now(), data: data };
    MEM.set(ns + '|' + key, entry);
    try {
      sessionStorage.setItem(storageKey(ns, key), JSON.stringify(entry));
      _addManifest(ns, key);
    } catch (e) { /* 隐私模式 / 配额：退化为内存层 */ }
    return entry;
  }

  function get(ns, key) {
    var mk = ns + '|' + key;
    if (MEM.has(mk)) return MEM.get(mk);
    try {
      var raw = sessionStorage.getItem(storageKey(ns, key));
      if (raw) { var e = JSON.parse(raw); MEM.set(mk, e); return e; }
    } catch (e) {}
    return null;
  }

  // 清指定条目（key 给定）或整命名空间（key 省略）。仅清本地，不广播。
  function purge(ns, key) {
    if (key !== undefined && key !== null) {
      MEM.delete(ns + '|' + key);
      try { sessionStorage.removeItem(storageKey(ns, key)); _removeManifest(ns, key); } catch (e) {}
    } else {
      var keys = _manifestKeys(ns);
      keys.forEach(function (k) {
        MEM.delete(ns + '|' + k);
        try { sessionStorage.removeItem(storageKey(ns, k)); } catch (e) {}
      });
      _clearManifest(ns);
    }
  }

  function purgeAll() {
    Object.keys(NS).forEach(function (k) { purge(NS[k]); });
  }

  // 写成功后广播失效：本 tab 派发 ih:invalidate；其余 tab 经 storage 事件收到后 purge。
  function broadcast(ns, key) {
    try {
      var sig = { ns: ns, key: key || null, ts: Date.now() };
      localStorage.setItem(INVALIDATIONS_KEY, JSON.stringify(sig));
      global.dispatchEvent(new CustomEvent('ih:invalidate', { detail: sig }));
    } catch (e) {}
  }

  // 跨 tab：其他 tab 写入 invalidations 时，本 tab 清本地缓存并广播给本 tab 的 UI。
  global.addEventListener('storage', function (e) {
    if (e.key === INVALIDATIONS_KEY && e.newValue) {
      try {
        var sig = JSON.parse(e.newValue);
        purge(sig.ns, sig.key || null);
        global.dispatchEvent(new CustomEvent('ih:invalidate', { detail: sig }));
      } catch (_) {}
    }
  });

  global.CacheStore = {
    NS: NS,
    fp: fp,
    set: set,
    get: get,
    purge: purge,
    purgeAll: purgeAll,
    broadcast: broadcast,
    storageKey: storageKey,
    MANIFEST_KEY: MANIFEST_KEY
  };
})(window);
