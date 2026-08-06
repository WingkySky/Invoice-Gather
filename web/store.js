/* ======================================================== 票归集 · 全局 store + API 客户端
 * GlobalStore : 跨视图共享的数据状态（pub-sub），P1·F 全量进内存后作为主数据集。
 * ApiClient   : 封装 get/post。
 *   - get(ns, url, opts)：先查 CacheStore（内存 / session）；
 *       命中且版本有效 → 立即回调渲染并打"更新中"角标；
 *       同时后台 fetch 比对 X-Data-Version，相同跳过重渲染，增大则更新并移除角标。
 *   - post(url, body, opts)：成功后按 opts.invalidate 的命名空间 purge 缓存
 *       + 写 localStorage['ih:invalidations'] + 派发 ih:invalidate（跨 tab 经 storage 同步 purge）。
 */
(function (global) {
  'use strict';

  var CacheStore = global.CacheStore;

  // ----------------------------------------------------------- GlobalStore（pub-sub）
  var GlobalStore = (function () {
    var state = {
      invoices: [], companies: [], accounts: [], filters: {}, stats: null,
      meta: { dataVersion: 0, lastFetchTs: 0 }
    };
    var listeners = new Set();
    function getState() { return state; }
    function setState(patch) { Object.assign(state, patch); emit('state', state); }
    function subscribe(fn) { listeners.add(fn); return function () { listeners.delete(fn); }; }
    function emit(evt, payload) {
      listeners.forEach(function (fn) { try { fn(evt, payload); } catch (e) {} });
    }
    return { getState: getState, setState: setState, subscribe: subscribe, emit: emit };
  })();

  // ----------------------------------------------------------- ApiClient
  var ApiClient = {
    /**
     * 只读 GET，带缓存优先 + 后台静默刷新。
     * opts:
     *   filters : 用于计算缓存 fingerprint 的筛选条件对象
     *   onData(data, meta)  : 数据变化（或首次无缓存）时回调，用于渲染
     *   onSame(data)        : 版本未变，无需重渲染（用于移除"更新中"角标）
     *   onStale(data, ts)   : 后台刷新失败但有旧缓存，用于标注"X 分钟前数据"
     */
    get: function (ns, url, opts) {
      opts = opts || {};
      var filters = opts.filters || {};
      var key = CacheStore.fp(filters);
      var cached = CacheStore.get(ns, key);

      // 同步立即用缓存快照渲染（若有）：进页面 <200ms 秒显，并打"更新中"角标。
      if (cached && typeof opts.onCache === 'function') {
        try { opts.onCache(cached.data, { version: cached.v, ts: cached.ts }); }
        catch (e) {}
      }

      // 后台静默刷新：比对 X-Data-Version。
      return fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(function (resp) {
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          return resp.json().then(function (data) {
            var sver = parseInt(resp.headers.get('X-Data-Version') || '0', 10) || 0;
            GlobalStore.setState({ meta: { dataVersion: sver, lastFetchTs: Date.now() } });
            if (cached && cached.v === sver) {
              // 数据未变：保留缓存，跳过重渲染（仅移除"更新中"角标）。
              if (typeof opts.onSame === 'function') opts.onSame(cached.data);
              return { data: cached.data, version: sver, changed: false, fromCache: true };
            }
            // 数据已变或首次：写入缓存并渲染。
            CacheStore.set(ns, key, data, sver);
            if (typeof opts.onData === 'function') opts.onData(data, { version: sver, changed: true });
            return { data: data, version: sver, changed: true, fromCache: false };
          });
        })
        .catch(function (e) {
          if (cached) {
            // 后台刷新失败但有旧缓存：保留快照（onStale 负责标注"X 分钟前数据"）。
            if (typeof opts.onStale === 'function') opts.onStale(cached.data, cached.ts);
            else if (typeof opts.onData === 'function') opts.onData(cached.data, { cached: true, stale: true });
            return { data: cached.data, version: cached.v, changed: false, fromCache: true, error: e };
          }
          // 无缓存且请求失败：交由 onError 处理（如骨架→错误提示）。
          if (typeof opts.onError === 'function') opts.onError(e);
          throw e;
        });
    },

    /**
     * 写操作 POST。成功后按 opts.invalidate（字符串或数组）purge 对应命名空间缓存，
     * 并广播失效（跨 tab 同步）。返回解析后的响应对象。
     */
    post: function (url, body, opts) {
      opts = opts || {};
      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (r.ok && opts.invalidate) {
            var nsList = Array.isArray(opts.invalidate) ? opts.invalidate : [opts.invalidate];
            nsList.forEach(function (ns) { CacheStore.purge(ns); });
            if (nsList.length) CacheStore.broadcast(nsList[0], null);
          }
          return data;
        });
      });
    }
  };

  global.GlobalStore = GlobalStore;
  global.ApiClient = ApiClient;
})(window);
