// ==UserScript==
// @name         一键录卡
// @author       Codex
// @version      0.9.14
// @description  用户主动选择后识别、录入并绘制主流人物卡；支持在海豹后台配置AI评分并接入宝可元Token计费
// @timestamp    1784736000
// @license      MIT
// ==/UserScript==

(function () {
  'use strict';

  const EXT_NAME = '一键录卡';
  let ext = seal.ext.find(EXT_NAME);
  if (ext) return;
  ext = seal.ext.new(EXT_NAME, 'Codex', '0.9.14');
  seal.ext.register(ext);

  seal.ext.registerStringConfig(ext, '服务地址', 'http://127.0.0.1:8765', '一键录卡 HTTP 服务地址', '连接');
  seal.ext.registerStringConfig(ext, 'API令牌', 'change-me', '需与 AUTOCARD_API_TOKEN 一致', '连接');
  seal.ext.registerStringConfig(ext, 'AI评分API地址', '', '填写 OpenAI 兼容接口基址、/v1 地址或完整 /chat/completions 地址', 'AI评分');
  seal.ext.registerStringConfig(ext, 'AI评分API密钥', '', '仅用于本机一键录卡后端发起评分请求，不会放入图片地址', 'AI评分');
  seal.ext.registerStringConfig(ext, 'AI评分模型', 'deepseek-v4-flash', '填写接口支持的模型名称', 'AI评分');
  seal.ext.registerIntConfig(ext, '等待确认分钟', 30, '上传后允许确认的时间', '流程');
  seal.ext.registerIntConfig(ext, '官方QQ图片按钮延迟秒', 4, '公网 Markdown 图片不可用、必须分成两个气泡时，等待图片先显示再发送按钮', '流程');

  function config(key) {
    return seal.ext.getStringConfig(ext, key);
  }

  function reviewAISettings() {
    const serviceUrl = String(config('服务地址') || '').trim();
    const apiUrl = String(config('AI评分API地址') || '').trim();
    const apiKey = String(config('AI评分API密钥') || '').trim();
    const model = String(config('AI评分模型') || '').trim();
    if (!apiUrl || !apiKey || !model) {
      return {
        ok: false,
        error: '角色卡AI评分尚未配置。请到海豹 WebUI → 扩展 → 一键录卡 → 配置，填写「AI评分API地址」、「AI评分API密钥」和「AI评分模型」。'
      };
    }
    if (!/^https?:\/\//i.test(apiUrl)) {
      return { ok: false, error: '「AI评分API地址」必须以 http:// 或 https:// 开头。' };
    }
    if (!/^https?:\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:\/|$)/i.test(serviceUrl)) {
      return { ok: false, error: '为了保护AI密钥，「服务地址」必须使用本机 127.0.0.1、localhost 或 [::1]。' };
    }
    return { ok: true, value: { api_url: apiUrl, api_key: apiKey, model: model } };
  }

  function isOfficialQQ(ctx, msg) {
    const values = [];
    try { values.push(msg && msg.platform); } catch (_) {}
    try { values.push(msg && msg.sender && msg.sender.userId); } catch (_) {}
    try { values.push(msg && msg.groupId); } catch (_) {}
    try { values.push(ctx && ctx.player && ctx.player.userId); } catch (_) {}
    try { values.push(ctx && ctx.group && ctx.group.groupId); } catch (_) {}
    try { values.push(ctx && ctx.endPoint && ctx.endPoint.platform); } catch (_) {}
    return values.some(value => /^(?:OpenQQ(?:CH)?(?:[-:]|$)|QQ-official$)/i.test(String(value || '').trim()));
  }

  function officialQQButtonMarker(ctx, msg, buttons) {
    if (!isOfficialQQ(ctx, msg) || !Array.isArray(buttons)) return '';
    const items = [];
    buttons.forEach(item => {
      if (!item || items.length >= 5) return;
      let label = String(item.label || '').trim().replace(/[|;\[\]\r\n]/g, '');
      const data = String(item.data || '').trim();
      label = Array.from(label).slice(0, 10).join('');
      if (!label || !data || data[0] !== '.' || data.length > 128 || /[|;\[\]\r\n]/.test(data)) return;
      items.push(label + '|' + data);
    });
    return items.length
      ? '\n[SealDice-OfficialQQ-InputButtons:' + items.join(';') + ']'
      : '';
  }

  function withOfficialQQButtons(ctx, msg, text, buttons) {
    return String(text || '') + officialQQButtonMarker(ctx, msg, buttons);
  }

  function waitMilliseconds(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, Math.max(0, Number(milliseconds) || 0)));
  }

  function ruleSwitchButton(sealSystem) {
    if (sealSystem === 'coc7') return { label: '切换COC规则', data: '.set coc' };
    if (sealSystem === 'dnd5e') return { label: '切换DND规则', data: '.set dnd' };
    if (sealSystem === 'pokemon') return { label: '切换旅伴规则', data: '.set pkm' };
    return null;
  }

  function serviceOpenNow(ctx, msg) {
    // QQ 官方机器人（OpenQQ/OpenQQCH）不需要夜间低调，全天开放。
    if (isOfficialQQ(ctx, msg)) return true;
    // 固定使用北京时间，避免服务器系统时区不同导致开放时间漂移。
    const beijingHour = new Date(Date.now() + 8 * 60 * 60 * 1000).getUTCHours();
    return beijingHour >= 10 && beijingHour < 23;
  }

  function replySleeping(ctx, msg) {
    seal.replyToSender(ctx, msg, '睡啦睡啦，白天在录吧😴');
  }

  function identityHub() {
    try {
      const target = seal.ext.find('跨平台身份中心');
      if (target && target.identityHub) return target.identityHub;
    } catch (_) {}
    try {
      if (globalThis.SealIdentityHubV1) return globalThis.SealIdentityHubV1;
    } catch (_) {}
    return null;
  }

  function registerCharacterProfile(ctx, msg, character) {
    const hub = identityHub();
    if (!hub || !hub.upsertRole || !character) return null;
    try {
      return hub.upsertRole(ctx, msg, character);
    } catch (_) {
      return null;
    }
  }

  const FISHING_EXT_NAME = 'fishingSystemV2';
  const FISHING_STORAGE_SUFFIX = '_pokemon_fish_v1';
  const REVIEW_TOKEN_STEP = 50000;
  const REVIEW_STEP_CHARGE = 100;
  const REVIEW_MIN_CHARGE = 100;
  const reviewLocks = Object.create(null);

  function fishingUserIds(ctx, msg) {
    const result = [];
    function add(value) {
      const normalized = String(value || '').trim();
      if (normalized && result.indexOf(normalized) < 0) result.push(normalized);
      const colon = normalized.lastIndexOf(':');
      if (colon >= 0 && colon < normalized.length - 1) {
        const suffix = normalized.slice(colon + 1).trim();
        if (suffix && result.indexOf(suffix) < 0) result.push(suffix);
      }
    }
    try { add(ctx && ctx.player && ctx.player.userId); } catch (_) {}
    try { add(msg && msg.sender && msg.sender.userId); } catch (_) {}
    try { add(ctx && ctx.userId); } catch (_) {}
    try { add(ctx && ctx.player && ctx.player.id); } catch (_) {}
    try { add(msg && msg.sender && msg.sender.id); } catch (_) {}
    try {
      if (seal.identity && typeof seal.identity.canonicalUserId === 'function') {
        add(seal.identity.canonicalUserId(ctx, msg));
      }
    } catch (_) {}
    return result;
  }

  function fishingAccountScore(data, candidateIndex) {
    const fields = [
      'total', 'success', 'collection', 'shinyCollection', 'inventory',
      'history', 'lastDate', 'dailyCount', 'goods_inventory', 'fishingTasks',
      'work', 'legendaryHistory', 'collectionMilestonesClaimed'
    ];
    let evidence = 0;
    fields.forEach(name => {
      if (Object.prototype.hasOwnProperty.call(data, name)) evidence += 1;
    });
    const coins = Math.floor(Number(data.coins) || 0);
    return evidence * 1000000000 + Math.max(-1000000, Math.min(1000000, coins)) * 100 - candidateIndex;
  }

  function loadFishingAccounts(ctx, msg) {
    let fishing = null;
    try { fishing = seal.ext.find(FISHING_EXT_NAME); } catch (_) {}
    if (!fishing || typeof fishing.storageGet !== 'function' || typeof fishing.storageSet !== 'function') {
      return { ok: false, error: '没有找到宝可梦钓鱼插件，暂时无法使用付费AI评分。' };
    }
    const ids = fishingUserIds(ctx, msg);
    if (!ids.length) return { ok: false, error: '没有读取到你的用户ID。' };
    const accounts = [];
    let parseFailed = false;
    ids.forEach((id, index) => {
      const key = id + FISHING_STORAGE_SUFFIX;
      let raw = '';
      try { raw = String(fishing.storageGet(key) || ''); } catch (_) { return; }
      if (!raw) return;
      try {
        const parsed = JSON.parse(raw);
        const data = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
        accounts.push({
          ext: fishing,
          key: key,
          raw: raw,
          data: data,
          coins: Math.floor(Number(data.coins) || 0),
          score: fishingAccountScore(data, index)
        });
      } catch (_) {
        parseFailed = true;
      }
    });
    if (!accounts.length) {
      return {
        ok: false,
        error: parseFailed
          ? '宝可元账户读取失败，为保护钓鱼存档已停止评分。'
          : '没有找到你的宝可元账户，请先发送 .宝可元 建立账户。'
      };
    }
    accounts.sort((left, right) => right.score - left.score);
    return { ok: true, accounts: accounts, primary: accounts[0] };
  }

  function reviewBillingPrecheck(ctx, msg) {
    const loaded = loadFishingAccounts(ctx, msg);
    if (!loaded.ok) return loaded;
    const primary = loaded.primary;
    if (primary.coins < 0 || primary.data.isDebtor === true) {
      return {
        ok: false,
        error: '你当前负债 ' + Math.max(0, -primary.coins) + ' 宝可元，余额为 ' + primary.coins +
          '。还清负债前无法使用角色卡AI评分；可以通过 .钓鱼 或 .打工 赚取宝可元。'
      };
    }
    return loaded;
  }

  function calculateReviewCharge(totalTokens) {
    const tokens = Math.max(0, Math.floor(Number(totalTokens) || 0));
    return Math.max(REVIEW_MIN_CHARGE, Math.max(1, Math.ceil(tokens / REVIEW_TOKEN_STEP)) * REVIEW_STEP_CHARGE);
  }

  function settleReviewCharge(loaded, chargeId, amount, totalTokens) {
    const safeAmount = Math.max(1, Math.floor(Number(amount) || REVIEW_MIN_CHARGE));
    const safeTokens = Math.max(0, Math.floor(Number(totalTokens) || 0));
    const written = [];
    try {
      loaded.accounts.forEach(account => {
        const records = Array.isArray(account.data._autocard_review_charges)
          ? account.data._autocard_review_charges.slice()
          : [];
        const duplicate = records.some(item => item && String(item.id || '') === chargeId);
        if (!duplicate) {
          const balance = Math.floor(Number(account.data.coins) || 0) - safeAmount;
          account.data.coins = balance;
          const wasDebtor = account.data.isDebtor === true;
          account.data.isDebtor = balance < 0 || (wasDebtor && balance <= 0);
          account.data.debt = account.data.isDebtor ? Math.max(0, -balance) : 0;
          records.push({
            id: chargeId,
            amount: safeAmount,
            total_tokens: safeTokens,
            balance: balance,
            charged_at: Math.floor(Date.now() / 1000)
          });
          account.data._autocard_review_charges = records.slice(-100);
          account.ext.storageSet(account.key, JSON.stringify(account.data));
          written.push(account);
        }
        const verified = JSON.parse(String(account.ext.storageGet(account.key) || '{}'));
        if (!Array.isArray(verified._autocard_review_charges) ||
            !verified._autocard_review_charges.some(item => item && String(item.id || '') === chargeId)) {
          throw new Error('扣款记录写入校验失败：' + account.key);
        }
        account.data = verified;
        account.coins = Math.floor(Number(verified.coins) || 0);
      });
    } catch (error) {
      written.forEach(account => {
        try { account.ext.storageSet(account.key, account.raw); } catch (_) {}
      });
      throw error;
    }
    const primary = loaded.accounts.find(account => account.key === loaded.primary.key) || loaded.accounts[0];
    return {
      balance: Math.floor(Number(primary.data.coins) || 0),
      accountCount: loaded.accounts.length,
      amount: safeAmount,
      totalTokens: safeTokens
    };
  }

  function reviewRequestId(ctx, msg, token) {
    const user = fishingUserIds(ctx, msg)[0] || 'unknown';
    return 'autocard-' + String(token || '').slice(0, 32) + '-' +
      Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10) + '-' +
      String(user).replace(/[^A-Za-z0-9_-]/g, '').slice(-20);
  }

  function pendingMap() {
    try {
      const raw = ext.storageGet('pending_cards');
      return raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
  }

  function savePending(map) {
    ext.storageSet('pending_cards', JSON.stringify(map));
  }

  function lastMap() {
    try {
      const raw = ext.storageGet('last_cards');
      return raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
  }

  function saveLast(map) {
    ext.storageSet('last_cards', JSON.stringify(map));
  }

  function candidateMap() {
    try {
      const raw = ext.storageGet('group_card_files');
      return raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
  }

  function saveCandidates(map) {
    ext.storageSet('group_card_files', JSON.stringify(map));
  }

  function fileScopeKey(ctx, msg) {
    const group = ctx.group && ctx.group.groupId ? String(ctx.group.groupId) : '';
    if (group) return group;
    const user = (msg.sender && msg.sender.userId) || (ctx.player && ctx.player.userId) || 'unknown';
    return 'private|' + user;
  }

  function groupLabel(ctx, msg) {
    const group = ctx.group || {};
    const name = String(group.groupName || group.name || '').trim();
    const id = String(group.groupId || msg.groupId || '').trim();
    if (name && id) return name + '（' + id + '）';
    return name || id || '当前私聊';
  }

  function candidateFiles(ctx, msg) {
    const map = candidateMap();
    const key = fileScopeKey(ctx, msg);
    const cutoff = Date.now() - 24 * 60 * 60 * 1000;
    const items = Array.isArray(map[key])
      ? map[key]
        .filter(item => Number(item.createdAt || 0) >= cutoff)
        .map(normalizeExcelCandidate)
        .filter(Boolean)
      : [];
    if (items.length !== (map[key] || []).length) {
      map[key] = items;
      saveCandidates(map);
    }
    return items;
  }

  function rememberCandidate(ctx, msg, file) {
    const map = candidateMap();
    const key = fileScopeKey(ctx, msg);
    const current = candidateFiles(ctx, msg);
    const identity = String(file.fileId || file.url || file.filename || '');
    const deduplicated = current.filter(item =>
      String(item.fileId || item.url || item.filename || '') !== identity
    );
    let uploader = '';
    try {
      uploader = String(
        (msg.sender && (msg.sender.nickname || msg.sender.name || msg.sender.userId)) ||
        (ctx.player && (ctx.player.name || ctx.player.userId)) || ''
      );
    } catch (_) {}
    deduplicated.push(Object.assign({}, file, {
      uploader: uploader,
      createdAt: Date.now()
    }));
    map[key] = deduplicated.slice(-12);
    saveCandidates(map);
    return map[key];
  }

  function fileSizeText(value) {
    const size = Number(value || 0);
    if (!Number.isFinite(size) || size <= 0) return '';
    if (size >= 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + ' MB';
    if (size >= 1024) return Math.round(size / 1024) + ' KB';
    return Math.round(size) + ' B';
  }

  function timeText(timestamp) {
    const date = new Date(Number(timestamp || Date.now()));
    const pad = value => String(value).padStart(2, '0');
    return pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' +
      pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  function scopeKey(ctx, msg) {
    const group = ctx.group && ctx.group.groupId ? ctx.group.groupId : 'private';
    const user = (msg.sender && msg.sender.userId) || (ctx.player && ctx.player.userId) || 'unknown';
    return group + '|' + user;
  }

  function getPending(ctx, msg) {
    const map = pendingMap();
    const item = map[scopeKey(ctx, msg)];
    if (!item) return null;
    const maxAge = seal.ext.getIntConfig(ext, '等待确认分钟') * 60 * 1000;
    if (Date.now() - item.createdAt > maxAge) {
      delete map[scopeKey(ctx, msg)];
      savePending(map);
      return null;
    }
    return item;
  }

  function setPending(ctx, msg, item) {
    const map = pendingMap();
    map[scopeKey(ctx, msg)] = Object.assign({ createdAt: Date.now() }, item);
    savePending(map);
  }

  function setLast(ctx, msg, item) {
    const map = lastMap();
    map[scopeKey(ctx, msg)] = Object.assign({ createdAt: Date.now() }, item);
    saveLast(map);
  }

  function getLast(ctx, msg) {
    const map = lastMap();
    const key = scopeKey(ctx, msg);
    const item = map[key];
    if (!item) return null;
    const maxAge = seal.ext.getIntConfig(ext, '等待确认分钟') * 60 * 1000;
    if (Date.now() - item.createdAt > maxAge) {
      delete map[key];
      saveLast(map);
      return null;
    }
    return item;
  }

  function clearPending(ctx, msg) {
    const map = pendingMap();
    delete map[scopeKey(ctx, msg)];
    savePending(map);
  }

  async function api(path, options) {
    const response = await fetch(config('服务地址').replace(/\/$/, '') + path, Object.assign({
      headers: {
        'Authorization': 'Bearer ' + config('API令牌'),
        'Content-Type': 'application/json'
      }
    }, options || {}));
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }

  // Portrait ownership must follow the account identity, never the official
  // QQ group nickname.  Send every stable identity alias available so the
  // log renderer can still match cards after .bind migrations.
  function portraitOwnerIDs(ctx, msg) {
    const result = [];
    function add(value) {
      const id = String(value || '').trim();
      if (id && result.indexOf(id) < 0) result.push(id);
    }
    try { add(ctx && ctx.player && ctx.player.userId); } catch (_) {}
    try { add(msg && msg.sender && msg.sender.userId); } catch (_) {}
    try { add(ctx && ctx.userId); } catch (_) {}
    try {
      if (seal.identity && typeof seal.identity.canonicalUserId === 'function') {
        add(seal.identity.canonicalUserId(ctx, msg));
      }
    } catch (_) {}
    return result.slice(0, 12);
  }

  function renderPortraitCard(ctx, msg, token) {
    return api('/api/v1/render/' + token, {
      method: 'POST',
      body: JSON.stringify({ owner_ids: portraitOwnerIDs(ctx, msg) })
    });
  }

  function cqUnescape(value) {
    return String(value || '')
      .replace(/&#44;/g, ',').replace(/&#91;/g, '[').replace(/&#93;/g, ']')
      .replace(/&amp;/g, '&');
  }

  function safeDecode(value) {
    let text = cqUnescape(String(value || ''));
    for (let index = 0; index < 2; index += 1) {
      try {
        const decoded = decodeURIComponent(text.replace(/\+/g, '%20'));
        if (decoded === text) break;
        text = decoded;
      } catch (_) {
        break;
      }
    }
    return text;
  }

  function excelFormatFrom() {
    for (let index = 0; index < arguments.length; index += 1) {
      const match = safeDecode(arguments[index]).match(/\.(xlsx|xlsm|xls)(?:$|[?#&/])/i);
      if (match) return match[1].toLowerCase();
    }
    return '';
  }

  function filenameFromDownloadUrl(rawUrl) {
    const decoded = safeDecode(rawUrl);
    // Official QQ currently uses `fname`, while different QQ adapters may
    // expose filename/name/attname instead. Keep all of them compatible.
    const queryMatch = decoded.match(/[?&](?:fname|filename|file_name|name|attname|download)=([^&#]+)/i);
    if (queryMatch) {
      const candidate = safeDecode(queryMatch[1]).split(/[\\/]/).pop();
      if (/\.(xlsx|xlsm|xls)$/i.test(candidate)) return candidate;
    }
    const pathName = decoded.split(/[?#]/)[0].split(/[\\/]/).pop();
    return /\.(xlsx|xlsm|xls)$/i.test(pathName) ? pathName : '';
  }

  function normalizeExcelCandidate(file) {
    if (!file || typeof file !== 'object') return null;
    const format = String(file.format || '').toLowerCase() || excelFormatFrom(
      file.filename, file.name, file.fileName, file.file, file.url
    );
    if (!/^(xlsx|xlsm|xls)$/.test(format)) return null;
    let filename = safeDecode(file.filename || file.name || file.fileName || '');
    const downloadSource = file.url || file.file || filename;
    // Do not mistake `hash?fname=角色名.xlsx` for the literal filename. This
    // shape is emitted by the Official QQ adapter for uploaded attachments.
    if (/^https?:\/\//i.test(filename) || /[?&](?:fname|filename|file_name|name|attname|download)=/i.test(filename)) {
      filename = filenameFromDownloadUrl(downloadSource) || filenameFromDownloadUrl(filename);
    }
    filename = filename.split(/[\\/]/).pop().split(/[?#]/)[0];
    if (!/\.(xlsx|xlsm|xls)$/i.test(filename)) {
      filename = filenameFromDownloadUrl(downloadSource);
    }
    if (!filename) {
      const fingerprint = String(file.fileId || file.file_id || file.file || '附件')
        .replace(/[^A-Za-z0-9_-]/g, '')
        .slice(0, 12) || '附件';
      filename = '官方QQ附件_' + fingerprint + '.' + format;
    } else if (!/\.(xlsx|xlsm|xls)$/i.test(filename)) {
      filename += '.' + format;
    }
    return Object.assign({}, file, { filename: filename, format: format });
  }

  function fileFromMessage(message) {
    const text = String(message || '');
    const match = text.match(/\[CQ:file,([^\]]+)\]/i);
    if (match) {
      const params = {};
      match[1].split(',').forEach(part => {
        const index = part.indexOf('=');
        if (index > 0) params[part.slice(0, index)] = cqUnescape(part.slice(index + 1));
      });
      const rawFile = params.file || '';
      const fileId = params.file_id || params.fileId || params.fid || '';
      const url = params.url || (/^https?:\/\//i.test(rawFile) ? rawFile : '');
      const candidate = normalizeExcelCandidate({
          filename: params.name || params.filename || params.file_name || rawFile,
          file: rawFile,
          url: url,
          fileId: fileId,
          busid: Number(params.busid || params.file_type || 3) || 3,
          size: Number(params.file_size || params.size || 0) || 0
      });
      if ((url || fileId) && candidate) return candidate;
    }
    try {
      const value = JSON.parse(text);
      const data = value.data || value;
      const fileId = data.file_id || data.fileId || data.fid || '';
      const rawFile = data.file || '';
      const url = data.url || (/^https?:\/\//i.test(rawFile) ? rawFile : '');
      const candidate = normalizeExcelCandidate({
          filename: data.name || data.filename || data.file_name || rawFile,
          file: rawFile,
          url: url,
          fileId: fileId,
          busid: Number(data.busid || data.file_type || 3) || 3,
          size: Number(data.file_size || data.size || 0) || 0
      });
      if ((url || fileId) && candidate) return candidate;
    } catch (_) {}
    const urlMatch = text.match(/https?:\/\/[^\s\]]+/i);
    if (urlMatch && /\.(xlsx|xlsm|xls)(?:$|[?#])/i.test(urlMatch[0])) {
      return normalizeExcelCandidate({ filename: filenameFromDownloadUrl(urlMatch[0]), url: urlMatch[0] });
    }
    return null;
  }

  function currentSystem(ctx) {
    try {
      const value = seal.vars.strGet(ctx, '$t游戏模式');
      return String(value[0] || '').toLowerCase();
    } catch (_) {
      try { return String(seal.format(ctx, '{$t游戏模式}') || '').toLowerCase(); } catch (_) { return ''; }
    }
  }

  function pokemonExtension() {
    const names = [
      '门版宝可梦TRPG综合助手v1.38.61',
      '门版宝可梦TRPG综合助手v1.38.60',
      '门版宝可梦TRPG综合助手v1.38.59',
      '门版宝可梦TRPG综合助手v1.38.58',
      '门版宝可梦TRPG综合助手v1.38.57',
      '门版宝可梦TRPG综合助手v1.38.56',
      '门版宝可梦TRPG综合助手v1.38.55',
      '门版宝可梦TRPG综合助手v1.38.53',
      '门版宝可梦TRPG综合助手v1.38.52',
      '门版宝可梦TRPG综合助手v1.38.51',
      '门版宝可梦TRPG综合助手'
    ];
    let fallback = null;
    let trainerOnly = null;
    for (let index = 0; index < names.length; index += 1) {
      const target = seal.ext.find(names[index]);
      if (!target) continue;
      if (!fallback) fallback = target;
      // cmdMap is a SealDice-managed bridge and remains callable even when
      // two JS extensions run in separate Goja realms.  Prefer it over
      // custom properties attached directly to an extension object.
      if (target.cmdMap && target.cmdMap.autocard_import_v1 &&
          typeof target.cmdMap.autocard_import_v1.solve === 'function') return target;
      const api = target.autocardApiV1;
      if (!api || typeof api.importTrainer !== 'function') continue;
      // Recent assistants intentionally reuse the historical v1.38.51 storage
      // namespace.  A stale v1.38.52 bridge can therefore coexist with it
      // and expose importTrainer without importRoster.  Do not return that
      // partial API before checking every registered alias for the complete
      // trainer + Pokemon roster interface.
      if (typeof api.importRoster === 'function') return target;
      if (!trainerOnly) trainerOnly = target;
    }
    return trainerOnly || fallback;
  }

  function systemMatches(ctx, expected) {
    if (!expected || expected === 'story') return true;
    if (expected === 'pokemon') return !!pokemonExtension() && currentSystem(ctx) === '旅伴规则';
    const current = currentSystem(ctx);
    if (!current) return true;
    return expected === 'coc7' ? current.indexOf('coc') >= 0 : current.indexOf('dnd') >= 0;
  }

  function mismatchText(expected) {
    if (expected === 'story') return '';
    if (expected === 'pokemon') {
      return '请安装配套宝可梦助手 v1.39.0 和私人核心旅伴角色卡版，发送 .set pkm，再用 .pc new 角色名 创建并绑定旅伴卡（已有卡用 .pc tag 角色名 切换）。';
    }
    return '当前群规则和人物卡不一致，请先发送 .set ' + (expected === 'coc7' ? 'coc' : 'dnd') + '（主要看人物卡的规则）；';
  }

  function discoveryText(ctx, msg, data, matches) {
    let text = isOfficialQQ(ctx, msg)
      ? '# 发现角色卡\n' +
        '## ' + data.character + '\n' +
        '> 文件：' + data.file + '（' + String(data.format).toUpperCase() + '）\n' +
        '> 规则：' + data.rule + '｜模板：' + data.template + '\n\n'
      : '发现了这是一张角色卡\n' +
        '文件：' + data.file + '（' + String(data.format).toUpperCase() + '）\n' +
        '规则：' + data.rule + ' | 模板：' + data.template + '\n' +
        '角色：' + data.character + '\n\n';
    if (data.seal_system === 'story') {
      text += '已可靠提取角色名与背景故事字段；此模板目前仅支持背景故事评审，不支持规则属性录入。';
    } else if (matches) {
      text += "一键录卡：回复 '.一键录卡 同意'";
    } else {
      text += mismatchText(data.seal_system) +
        "\n设置完成后，一键录卡：回复 '.一键录卡 同意'";
    }
    text += "\n角色卡评分：回复 '.角色卡评分'，让妖精评审官艾拉瞧瞧～";
    const buttons = [];
    if (data.seal_system !== 'story') {
      if (!matches) buttons.push(ruleSwitchButton(data.seal_system));
      buttons.push({ label: '同意录卡', data: '.一键录卡 同意' });
    }
    buttons.push({ label: '背景故事评分', data: '.角色卡评分' });
    return withOfficialQQButtons(ctx, msg, text, buttons);
  }

  async function discover(ctx, msg, file) {
    try {
      file = normalizeExcelCandidate(file) || file;
      const fileId = String(file.fileId || '').trim();
      let rawGroupId = '';
      try { rawGroupId = String((ctx.group && ctx.group.groupId) || msg.groupId || ''); } catch (_) {}
      const groupMatch = rawGroupId.match(/(\d+)$/);
      const groupId = groupMatch ? groupMatch[1] : rawGroupId;
      const endpoint = file.url ? '/api/v1/discover-url' : '/api/v1/discover-file-id';
      const requestBody = file.url
        ? { url: file.url, filename: file.filename }
        : {
            file_id: fileId,
            filename: file.filename,
            group_id: groupId,
            busid: Number(file.busid || 3) || 3
          };
      if (!file.url && !fileId) throw new Error('文件消息没有下载 URL 或 file_id');
      const data = await api(endpoint, {
        method: 'POST',
        body: JSON.stringify(requestBody)
      });
      setPending(ctx, msg, {
        token: data.token,
        rule: data.rule,
        sealSystem: data.seal_system,
        file: data.file,
        template: data.template,
        character: data.character
      });
      seal.replyToSender(ctx, msg, discoveryText(ctx, msg, data, systemMatches(ctx, data.seal_system)));
    } catch (error) {
      seal.replyToSender(ctx, msg, '人物卡识别失败：' + error.message);
    }
  }

  async function fileListImage(ctx, msg, files) {
    const displayFiles = files.map(item => ({
      filename: item.filename,
      format: item.format || excelFormatFrom(item.filename, item.url),
      size_text: fileSizeText(item.size),
      uploader: item.uploader || '',
      time_text: timeText(item.createdAt)
    }));
    return api('/api/v1/file-list', {
      method: 'POST',
      body: JSON.stringify({
        group_name: groupLabel(ctx, msg),
        files: displayFiles
      })
    });
  }

  function fileListButtonItems(files, imageOnly) {
    if (imageOnly) {
      return [
        { label: '导入刚上传文件', data: '.一键录卡 导入 最新' },
        { label: '录卡帮助', data: '.一键录卡 帮助' }
      ];
    }
    const buttons = files.slice(0, 5).map((_item, index) => ({
      label: '导入角色卡' + (index + 1),
      data: '.一键录卡 导入 ' + (index + 1)
    }));
    if (files.length > 5) {
      buttons[4] = { label: '导入最新文件', data: '.一键录卡 导入 最新' };
    }
    return buttons;
  }

  function replyFileListButtons(ctx, msg, files, imageOnly) {
    if (!isOfficialQQ(ctx, msg)) return;
    seal.replyToSender(ctx, msg, withOfficialQQButtons(
      ctx,
      msg,
      imageOnly ? '## 快捷导入\n> 请选择下一步操作' : '## 选择要读取的角色卡',
      fileListButtonItems(files, imageOnly)
    ));
  }

  function isPublicHttpsImage(url) {
    return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?\//i.test(String(url || '').trim());
  }

  function qqMarkdownImageDimension(value, fallback) {
    const parsed = Math.round(Number(value));
    return Number.isFinite(parsed) && parsed >= 1 && parsed <= 4096 ? parsed : fallback;
  }

  function officialQQFileListMarkdown(imageUrl, imageOnly, imageWidth, imageHeight, fileCount) {
    const heading = imageOnly
      ? '# 发现角色卡文件\n> 尚未读取文件内容，请选择下一步操作。'
      : '# 群内角色卡文件\n> 当前仅展示文件元数据，尚未读取任何文件内容。';
    const rows = Math.max(1, Math.min(12, Math.round(Number(fileCount)) || 1));
    const width = qqMarkdownImageDimension(imageWidth, 1400);
    const height = qqMarkdownImageDimension(imageHeight, 510 + rows * 112);
    return heading + '\n\n![群内角色卡文件 #' + width + 'px #' + height + 'px](' +
      String(imageUrl).trim() + ')';
  }

  async function showFileList(ctx, msg, prefix, imageOnly) {
    const files = candidateFiles(ctx, msg);
    if (!files.length) {
      seal.replyToSender(ctx, msg,
        '本群最近 24 小时没有检测到可用于录卡的 Excel 文件。\n' +
        '上传 .xls、.xlsx 或 .xlsm 后，骰娘只登记文件信息，不会自动读取。');
      return;
    }
    const intro = prefix || '【群内角色卡文件】\n当前仅展示文件元数据，尚未读取任何文件内容。';
    try {
      const data = await fileListImage(ctx, msg, files);
      if (isOfficialQQ(ctx, msg) && isPublicHttpsImage(data.image_url)) {
        seal.replyToSender(ctx, msg, withOfficialQQButtons(
          ctx,
          msg,
          officialQQFileListMarkdown(
            data.image_url,
            imageOnly,
            data.image_width,
            data.image_height,
            files.length
          ),
          fileListButtonItems(files, imageOnly)
        ));
      } else {
        seal.replyToSender(
          ctx,
          msg,
          (imageOnly ? '' : intro + '\n') + '[CQ:image,file=' + data.image_url + ',cache=0]'
        );
        if (isOfficialQQ(ctx, msg)) {
          const delaySeconds = Math.max(1, Math.min(15,
            Number(seal.ext.getIntConfig(ext, '官方QQ图片按钮延迟秒')) || 4));
          await waitMilliseconds(delaySeconds * 1000);
        }
        replyFileListButtons(ctx, msg, files, imageOnly);
      }
    } catch (error) {
      const lines = files.map((item, index) =>
        (index + 1) + '. ' + item.filename + (fileSizeText(item.size) ? '（' + fileSizeText(item.size) + '）' : '')
      );
      seal.replyToSender(ctx, msg, withOfficialQQButtons(ctx, msg, intro + '\n' + lines.join('\n') +
        '\n\n列表图片生成失败：' + error.message +
        '\n仍可发送 .一键录卡 导入 序号', fileListButtonItems(files, imageOnly)));
    }
  }

  async function importCandidate(ctx, msg, selector) {
    const files = candidateFiles(ctx, msg);
    if (!files.length) {
      seal.replyToSender(ctx, msg, '没有可导入的群文件，请先上传角色卡或发送 .一键录卡 列表。');
      return;
    }
    let index = -1;
    if (selector === '最新') {
      index = files.length - 1;
    } else {
      const number = Number(selector);
      if (Number.isInteger(number) && number >= 1 && number <= files.length) index = number - 1;
    }
    if (index < 0) {
      seal.replyToSender(ctx, msg, '序号无效。请先发送 .一键录卡 列表，再发送 .一键录卡 导入 1。');
      return;
    }
    const target = files[index];
    seal.replyToSender(ctx, msg,
      '已收到主动导入请求，现在开始读取：' + target.filename +
      '\n读取完成后会根据模板适配情况，提供录卡确认或背景故事评分指令。');
    await discover(ctx, msg, target);
  }

  function validVariableName(name) {
    return typeof name === 'string' && name.length > 0 && name.length <= 30 && !/[\s\[\]{}]/.test(name) && !name.includes('$', 1);
  }

  function cardImageMessages(ctx, msg, data) {
    const urls = Array.isArray(data.image_urls) && data.image_urls.length ? data.image_urls : [data.image_url];
    // A keyboard alone enables Markdown only on the final outgoing page in
    // some deployed cores. Explicitly mark the whole card as trusted Markdown
    // before the core splits it, so the trainer image also renders with the
    // global Markdown toggle off. This also keeps normal multi-card replies
    // within the core's single-message Markdown allowance (4000 UTF-8 bytes).
    const marker = isOfficialQQ(ctx, msg) ? '[SealDice-OfficialQQ-WelcomeMarkdown]\n' : '';
    return marker + urls.map((url, index) => {
      if (!url) throw new Error('后端没有返回角色卡图片地址');
      if (!isOfficialQQ(ctx, msg)) return '[CQ:image,file=' + url + ',cache=0]';
      if (!isPublicHttpsImage(url)) {
        throw new Error('官方QQ图片需要公网 HTTPS 地址，请将后端 AUTOCARD_PUBLIC_BASE_URL 配置为 https://autocard-api.example.com');
      }
      const size = (data.image_sizes || [])[index] || { width: 1600, height: 2200 };
      const width = Number(size.width) || 1600;
      const height = Number(size.height) || 2200;
      const scale = Math.min(1, 4096 / Math.max(width, height));
      return '![角色卡' + (index + 1) + ' #' + Math.max(1, Math.round(width * scale)) + 'px #' +
        Math.max(1, Math.round(height * scale)) + 'px](' + String(url).replace(/[()\s]/g, char => encodeURIComponent(char).replace(/\(/g, '%28').replace(/\)/g, '%29')) + ')';
    }).join('\n\n');
  }

  function characterVariableName(name) {
    const raw = String(name || '');
    // $stp_* is an internal DND saving-throw marker emitted deliberately by
    // the backend. Ordinary character-sheet fields must not carry "$":
    // "$力量" is a RollVM variable, while "力量" is the persistent card value.
    return raw.startsWith('$stp_') ? raw : raw.replace(/^\$+/, '');
  }

  function recordVariableName(name, rule) {
    let normalized = characterVariableName(name);
    if (String(rule || '').toUpperCase() !== 'COC7') return normalized;
    // Ω is used by some COC sheets as a visual skill marker. It must not be
    // included in the persistent SealDice variable name. Keeping this guard
    // in JS also repairs pending records created by an older Python backend.
    normalized = normalized.replace(/\s*[ΩΩ○●◎★☆※✓√✔]+\s*$/u, '').trim();
    const aliases = {
      '计算机使用': '计算机',
      '电脑': '计算机'
    };
    return aliases[normalized] || normalized;
  }

  function verifyIntegerWrites(ctx, expected, rule) {
    const failed = [];
    Object.keys(expected).forEach(name => {
      const targetName = recordVariableName(name, rule);
      if (!targetName || targetName.startsWith('$')) return;
      const wanted = Math.trunc(Number(expected[name]));
      if (!Number.isFinite(wanted)) return;
      try {
        const result = seal.vars.intGet(ctx, targetName);
        const actual = Array.isArray(result) ? Number(result[0]) : Number(result);
        const exists = !Array.isArray(result) || result.length < 2 || result[1] !== false;
        if (!exists || actual !== wanted) failed.push(targetName);
      } catch (_) {
        failed.push(targetName);
      }
    });
    if (failed.length) {
      throw new Error('海豹核心未保存这些人物卡属性：' + failed.slice(0, 8).join('、') +
        (failed.length > 8 ? '等' + failed.length + '项' : '') + '。录卡状态已保留，请更新插件后重试。');
    }
  }

  function verifyComputedWrites(ctx, expected, rule) {
    if (!seal.vars.computedGet) return;
    const failed = [];
    Object.keys(expected).forEach(name => {
      const targetName = recordVariableName(name, rule);
      const wanted = String(expected[name] || '');
      try {
        const result = seal.vars.computedGet(ctx, targetName);
        const actual = Array.isArray(result) ? String(result[0] || '') : String(result || '');
        const exists = !Array.isArray(result) || result.length < 2 || result[1] !== false;
        if (!exists || actual !== wanted) failed.push(targetName);
      } catch (_) {
        failed.push(targetName);
      }
    });
    if (failed.length) {
      throw new Error('海豹核心未保存这些动态技能：' + failed.slice(0, 8).join('、') +
        (failed.length > 8 ? '等' + failed.length + '项' : '') + '。录卡状态已保留，请更新插件后重试。');
    }
  }

  function applyRecord(ctx, record) {
    if (/^dnd/i.test(String(record.seal_system || record.rule || ''))) {
      return applyDndRecord(ctx, record);
    }
    let written = 0;
    Object.keys(record.values || {}).forEach(name => {
      const value = Number(record.values[name]);
      const targetName = recordVariableName(name, record.rule);
      if (!validVariableName(targetName) || !Number.isFinite(value)) return;
      seal.vars.intSet(ctx, targetName, Math.trunc(value));
      written += 1;
    });
    Object.keys(record.computed_values || {}).forEach(name => {
      const expression = String(record.computed_values[name] || '');
      const targetName = recordVariableName(name, record.rule);
      if (!validVariableName(targetName) || !/^pbCalc\([-+\d.]+,[-+\d.]+,[\u4e00-\u9fff]+\)$/.test(expression)) return;
      seal.vars.computedSet(ctx, targetName, expression);
      written += 1;
    });
    Object.keys(record.string_values || {}).forEach(name => {
      const value = String(record.string_values[name] || '');
      const targetName = recordVariableName(name, record.rule);
      if (!validVariableName(targetName) || !value) return;
      seal.vars.strSet(ctx, targetName, value);
    });
    // Do not report a successful import unless the core immediately reads
    // back the same persistent card values and computed skill expressions.
    verifyIntegerWrites(ctx, record.values || {}, record.rule);
    verifyComputedWrites(ctx, record.computed_values || {}, record.rule);
    if (record.name && ctx.player) {
      ctx.player.name = String(record.name);
      if ('updatedAtTime' in ctx.player) ctx.player.updatedAtTime = Math.floor(Date.now() / 1000);
    }
    return written;
  }

  const dndSkillParents = {
    '运动': '力量', '体操': '敏捷', '巧手': '敏捷', '隐匿': '敏捷',
    '调查': '智力', '奥秘': '智力', '历史': '智力', '自然': '智力', '宗教': '智力',
    '察觉': '感知', '洞悉': '感知', '驯兽': '感知', '医药': '感知', '求生': '感知',
    '游说': '魅力', '欺瞒': '魅力', '威吓': '魅力', '表演': '魅力'
  };

  function applyDndRecord(ctx, record) {
    if (!seal.vars.computedSet || !seal.vars.computedGet || !seal.format) {
      throw new Error('当前海豹核心缺少 DND 动态属性接口，尚未写入。');
    }
    const values = Object.assign({}, record.values || {});
    const computed = {};
    const metadata = [];
    Object.keys(dndSkillParents).forEach(name => {
      const parent = dndSkillParents[name];
      const raw = (record.computed_values || {})[name];
      let base = 0;
      let factor = 0;
      if (raw != null) {
        const match = /^pbCalc\(([-+\d.]+),([-+\d.]+),([\u4e00-\u9fff]+)\)$/.exec(String(raw));
        if (!match || match[3] !== parent) throw new Error('无法识别 DND 技能公式：' + name);
        base = Number(match[1]);
        factor = Number(match[2]);
      } else if (Object.prototype.hasOwnProperty.call(values, name)) {
        // Compatibility with pending records from pre-0.9.11 backends: their
        // scalar skills contain final totals, not native .st base bonuses.
        base = Number(values[name]) - Math.floor((Number(values[parent] ?? 10) - 10) / 2);
      }
      if (!Number.isFinite(base) || !Number.isFinite(factor)) throw new Error('DND 技能数值无效：' + name);
      delete values[name];
      computed[name] = 'pbCalc(this.base, this.factor, ' + parent + ')';
      metadata.push({ name, base, factor });
    });
    ['力量', '敏捷', '体质', '智力', '感知', '魅力'].forEach(name => {
      if (values['$stp_' + name] == null) values['$stp_' + name] = 0;
    });
    // Use the ordinary writer for scalar fields, then attach native computed
    // metadata. Only whitelisted skill names and finite numbers enter DiceScript.
    const count = applyRecord(ctx, Object.assign({}, record, {
      rule: '', seal_system: '', values, computed_values: {}
    }));
    metadata.forEach(item => {
      seal.vars.computedSet(ctx, item.name, computed[item.name]);
      seal.format(ctx, '{% &' + item.name + '.base = ' + item.base + '; &' + item.name + '.factor = ' + item.factor + '; "" %}');
      const saved = seal.format(ctx, '{&' + item.name + '.base}:{&' + item.name + '.factor}');
      if (saved !== item.base + ':' + item.factor) throw new Error('DND 技能元数据保存失败：' + item.name);
    });
    verifyComputedWrites(ctx, computed, record.rule);
    return count + metadata.length;
  }

  // onMessageReceived is the supported JS hook before BOTH native parsers.
  // onCommandReceived is too late; onCommandOverride is not exposed to JS.
  ext.onMessageReceived = (ctx, msg) => {
    if (!msg) return;
    const texts = Array.from(msg.segment || []).filter(segment => typeof segment.content === 'string');
    const joined = texts.map(segment => segment.content).join('');
    if (!/[.。!！/／]r(?:hd|dh|d)/i.test(String(msg.message || '') + joined)) return;
    // GroupInfo.system is not exposed by the real Goja binding. Temporary
    // variables may not yet exist at this early hook, so refresh via format.
    let system = '';
    try { system = String(seal.format(ctx, '{$t游戏模式}') || '').toLowerCase(); } catch (_) {}
    if (!/^dnd/.test(system)) return;
    function normalize(text) {
      const match = /^(\s*(?:\[CQ:at,[^\]]+\]\s*)*)([.。!！/／])r(hd|dh|d)\s*([\s\S]+)$/i.exec(String(text || ''));
      if (!match) return text;
      const reason = match[4].trim();
      if (!/^[A-Za-z\u3400-\u9fff]/.test(reason) ||
          /[+\-*/%=<>&|()[\]{}]|\d+d\d*|^d(?:\d|\s|$)|^(?:优势|劣势|優勢|劣勢|help\b)/i.test(reason)) return text;
      return match[1] + match[2] + (match[3].toLowerCase() === 'd' ? 'r' : 'rh') + ' d ' + reason;
    }
    msg.message = normalize(msg.message);
    const normalized = normalize(joined);
    if (texts.length && normalized !== joined) {
      texts[0].content = normalized;
      texts.slice(1).forEach(segment => { segment.content = ''; });
    }
  };

  function pokemonPstCmdArgs(parts) {
    const args = parts.slice();
    const rawArgs = args.join(' ');
    return {
      command: 'pst',
      args: args,
      kwargs: [],
      at: [],
      // Older SealDice JS bridges exposed this Go field with its original case.
      At: [],
      rawArgs: rawArgs,
      cleanArgs: rawArgs,
      rawText: '.pst ' + rawArgs,
      amIBeMentioned: false,
      amIBeMentionedFirst: false,
      specialExecuteTimes: 1,
      getArgN: index => index >= 1 && index <= args.length ? args[index - 1] : ''
    };
  }

  function readPokemonTrainerFromStorage(target, ctx, msg) {
    // v1.39 stores the record on the bound native character card. The
    // v1.38.61 assistant keeps the historical pokemon_player_data store.
    if (currentSystem(ctx) === '旅伴规则' && seal.character &&
        typeof seal.character.getCurrent === 'function' &&
        typeof seal.character.patchCurrent === 'function') {
      return pokemonNativeCard(ctx).ints || {};
    }
    let all = {};
    try {
      const raw = target.storageGet('pokemon_player_data');
      all = raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
    const ids = [];
    try { if (ctx && ctx.player && ctx.player.userId) ids.push(String(ctx.player.userId)); } catch (_) {}
    try { if (msg && msg.sender && msg.sender.userId) ids.push(String(msg.sender.userId)); } catch (_) {}
    for (let index = 0; index < ids.length; index += 1) {
      const record = all[ids[index]];
      if (!record || typeof record !== 'object') continue;
      return record.trainer && typeof record.trainer === 'object' ? record.trainer : record;
    }
    return {};
  }

  function readPokemonRosterFromStorage(target, ctx, msg) {
    if (currentSystem(ctx) === '旅伴规则' && seal.character &&
        typeof seal.character.getCurrent === 'function' &&
        typeof seal.character.patchCurrent === 'function') {
      const raw = (pokemonNativeCard(ctx).strings || {}).$pkmRecordV1;
      return raw ? JSON.parse(raw).pokemon || [] : [];
    }
    let all = {};
    try {
      const raw = target.storageGet('pokemon_player_data');
      all = raw ? JSON.parse(raw) : {};
    } catch (_) {
      return [];
    }
    const ids = [];
    try { if (ctx && ctx.player && ctx.player.userId) ids.push(String(ctx.player.userId)); } catch (_) {}
    try { if (msg && msg.sender && msg.sender.userId) ids.push(String(msg.sender.userId)); } catch (_) {}
    for (let index = 0; index < ids.length; index += 1) {
      const record = all[ids[index]];
      if (!record || typeof record !== 'object') continue;
      return Array.isArray(record.pokemon) ? record.pokemon : [];
    }
    return [];
  }

  function pokemonImportCmdArgs(payload) {
    const rawArgs = JSON.stringify(payload || {});
    return {
      command: 'autocard_import_v1',
      args: [rawArgs],
      kwargs: [],
      at: [],
      At: [],
      rawArgs: rawArgs,
      cleanArgs: rawArgs,
      rawText: '.autocard_import_v1 ' + rawArgs,
      autocardInternal: true,
      amIBeMentioned: false,
      amIBeMentionedFirst: false,
      specialExecuteTimes: 1,
      getArgN: index => index === 1 ? rawArgs : ''
    };
  }

  function failedPokemonWrites(values, stored) {
    return Object.keys(values).filter(name => {
      const wanted = Number(values[name]);
      return Number.isFinite(wanted) && Number(stored[name]) !== Math.trunc(wanted);
    });
  }

  function pokemonNativeCard(ctx) {
    if (currentSystem(ctx) !== '旅伴规则') throw new Error('请先发送 .set pkm 切换旅伴规则。');
    // v1.38.61 has the same rule name and a cross-extension import bridge,
    // but no native character-card API. Keep its legacy store usable.
    if (!seal.character || typeof seal.character.getCurrent !== 'function' ||
        typeof seal.character.patchCurrent !== 'function') {
      const legacy = pokemonExtension();
      if (legacy && legacy.cmdMap && legacy.cmdMap.autocard_import_v1 &&
          typeof legacy.cmdMap.autocard_import_v1.solve === 'function') {
        return { legacy: true, id: '', name: '' };
      }
      throw new Error('请先更新配套私人核心 v1.4.7（旅伴角色卡版）。');
    }
    const card = seal.character.getCurrent(ctx);
    if (!card.bound || card.sheetType !== '旅伴规则') {
      throw new Error('请先用 .pc new 角色名 创建并绑定旅伴卡，或 .pc tag 角色名 切换已有旅伴卡。当前卡未改动。');
    }
    return card;
  }

  function applyPokemonRecord(ctx, msg, record, expectedCardId) {
    const card = pokemonNativeCard(ctx);
    if (expectedCardId && card.id && card.id !== expectedCardId) throw new Error('生成卡图期间切换了角色卡，请确认目标后重新发送 .一键录卡 同意。');
    const target = pokemonExtension();
    if (!target) {
      throw new Error('未找到门版宝可梦TRPG综合助手，请安装配套 v1.38.61 或更高版本');
    }
    // The private core may expose seal.character even when the installed
    // Pokemon assistant is still v1.38.61. Detect the assistant by its own
    // version/API instead of treating the core capability as a v1.39 marker.
    const nativeApi = target.autocardApiV1;
    const importBridge = target.cmdMap && target.cmdMap.autocard_import_v1;
    const pluginText = String(target.version || target.name || '');
    const pluginMatch = pluginText.match(/(\d+)\.(\d+)/);
    const pluginMajor = pluginMatch ? Number(pluginMatch[1]) : NaN;
    const pluginMinor = pluginMatch ? Number(pluginMatch[2]) : NaN;
    const legacyApi = !!(nativeApi &&
      typeof nativeApi.importTrainer === 'function' &&
      typeof nativeApi.importRoster === 'function');
    const legacyPlugin = legacyApi && pluginMajor === 1 && Number.isFinite(pluginMinor) && pluginMinor < 39;
    const legacyBridge = !!(legacyPlugin || (card.legacy && importBridge &&
      typeof importBridge.solve === 'function'));
    if (!legacyBridge && !(pluginMajor > 1 || (pluginMajor === 1 && pluginMinor >= 39))) {
      throw new Error('请更新宝可梦助手至 v1.39.0 后再导入原生角色卡。');
    }
    const values = record.values || {};
    const roster = Array.isArray(record.pokemon) ? record.pokemon : [];
    const order = [
      'hpmax', 'hp', '旅行点', '物资点',
      '力量', '体魄', '智识', '意念', '机敏', '魅力', '幸运',
      '探查', '采集', '矿物', '植物', '传说', '宝可梦', '制球', '制香', '制药',
      '锻造', '医疗', '机械', '垂钓', '驾驶', '烹调', '运动', '对战', '协调',
      '骑乘', '表演', '声乐', '舞蹈', '绘画', '写作', '格斗术', '忍术',
      '超能力', '魔术', '潜伏', '妙手', '话术', '战斗术'
    ];
    const parts = [];
    const used = {};
    order.forEach(name => {
      const value = Number(values[name]);
      if (Number.isFinite(value)) {
        parts.push(name + String(Math.trunc(value)));
        used[name] = true;
      }
    });
    Object.keys(values).forEach(name => {
      const value = Number(values[name]);
      if (used[name] || !validVariableName(name) || !Number.isFinite(value)) return;
      parts.push(name + String(Math.trunc(value)));
    });
    if (!parts.length) throw new Error('没有可交给 .pst 的训练家属性');

    let imported = 0;
    let rosterImported = false;
    let nativeError = '';
    if (importBridge && typeof importBridge.solve === 'function') {
      try {
        importBridge.solve(ctx, msg, pokemonImportCmdArgs({
          protocol: 'sealdice-autocard-v1',
          storage: legacyBridge ? 'legacy-pokemon-data-v1' : 'native-pc-v1',
          expectedCardId: card.id || '',
          trainer: values,
          pokemon: roster
        }));
        const stored = readPokemonTrainerFromStorage(target, ctx, msg);
        const failed = failedPokemonWrites(values, stored);
        if (failed.length) throw new Error('未保存训练家属性：' + failed.slice(0, 8).join('、'));
        const savedRoster = readPokemonRosterFromStorage(target, ctx, msg);
        if (savedRoster.length !== roster.length) {
          throw new Error(`宝可梦队伍只保存了 ${savedRoster.length}/${roster.length} 只`);
        }
        imported = Object.keys(values).filter(name => Number.isFinite(Number(values[name]))).length;
        rosterImported = true;
      } catch (error) {
        throw new Error('宝可梦跨扩展录卡失败：' + String(error && error.message ? error.message : error));
      }
    } else if (nativeApi && typeof nativeApi.importTrainer === 'function') {
      try {
        const result = nativeApi.importTrainer(ctx, values);
        imported = result && Number(result.count || 0);
        if (!Number.isFinite(imported) || imported <= 0) {
          throw new Error('没有保存任何属性');
        }
        const stored = typeof nativeApi.readTrainer === 'function'
          ? (nativeApi.readTrainer(ctx) || {})
          : readPokemonTrainerFromStorage(target, ctx, msg);
        const failed = failedPokemonWrites(values, stored);
        if (failed.length) throw new Error('未保存：' + failed.slice(0, 8).join('、'));
      } catch (error) {
        nativeError = String(error && error.message ? error.message : error);
        imported = 0;
      }
    }

    // Compatibility path used by the original working release.  Build a full
    // CmdArgs-shaped object so getCtxProxyFirst/getArgN behave like a real .pst.
    if (imported <= 0) {
      if (!target.cmdMap || !target.cmdMap.pst || typeof target.cmdMap.pst.solve !== 'function') {
        throw new Error('宝可梦规则插件既没有可用的原生录卡接口，也没有 .pst 指令' +
          (nativeError ? '；原生接口错误：' + nativeError : ''));
      }
      try {
        target.cmdMap.pst.solve(ctx, msg, pokemonPstCmdArgs(parts));
      } catch (error) {
        const pstError = String(error && error.message ? error.message : error);
        throw new Error('宝可梦 .pst 兼容录卡失败：' + pstError +
          (nativeError ? '；原生接口错误：' + nativeError : ''));
      }
      const stored = readPokemonTrainerFromStorage(target, ctx, msg);
      const failed = failedPokemonWrites(values, stored);
      if (failed.length) {
        throw new Error('宝可梦 .pst 已执行，但未保存这些属性：' + failed.slice(0, 8).join('、'));
      }
      imported = Object.keys(values).filter(name => Number.isFinite(Number(values[name]))).length;
    }
    if (roster.length > 0 && !rosterImported) {
      if (!nativeApi || typeof nativeApi.importRoster !== 'function') {
        throw new Error('当前宝可梦规则插件没有跨扩展队伍录卡桥接。请更新至 v1.38.61 后重试');
      }
      let rosterResult;
      try {
        rosterResult = nativeApi.importRoster(ctx, roster);
      } catch (error) {
        throw new Error('保存宝可梦队伍失败：' + String(error && error.message ? error.message : error));
      }
      const rosterCount = Number(rosterResult && rosterResult.count);
      if (!Number.isFinite(rosterCount) || rosterCount !== roster.length) {
        throw new Error(`宝可梦队伍只保存了 ${Number.isFinite(rosterCount) ? rosterCount : 0}/${roster.length} 只`);
      }
      if (typeof nativeApi.readRoster === 'function') {
        const savedRoster = nativeApi.readRoster(ctx);
        if (!Array.isArray(savedRoster) || savedRoster.length !== roster.length) {
          throw new Error('宝可梦队伍写入后校验失败');
        }
      }
    }
    return imported;
  }

  ext.onNotCommandReceived = async (ctx, msg) => {
    const file = fileFromMessage(msg.message);
    if (!file) return;
    rememberCandidate(ctx, msg, file);
    if (!serviceOpenNow(ctx, msg)) return;
    await showFileList(ctx, msg, '', true);
  };

  const cmd = seal.ext.newCmdItemInfo();
  cmd.name = '一键录卡';
  cmd.help = '一键录卡 列表/导入 <序号|最新>/同意/重录/卡图；或 一键录卡 上传 <链接>';
  cmd.solve = async (ctx, msg, cmdArgs) => {
    if (!serviceOpenNow(ctx, msg)) {
      replySleeping(ctx, msg);
      return seal.ext.newCmdExecuteResult(true);
    }
    const action = String(cmdArgs.getArgN(1) || '').trim();
    if (!action || action === '帮助' || action.toLowerCase() === 'help' || action === '指令') {
      const helpTitle = isOfficialQQ(ctx, msg) ? '# 一键录卡\n## 指令帮助\n' : '【一键录卡指令】\n';
      seal.replyToSender(ctx, msg, withOfficialQQButtons(ctx, msg,
        helpTitle +
        '.一键录卡 列表 —— 查看本群最近 24 小时的候选文件\n' +
        '.一键录卡 导入 1 —— 主动读取列表中的第 1 个文件\n' +
        '.一键录卡 导入 最新 —— 主动读取最近上传的文件\n' +
        '.一键录卡 上传 <链接> —— 主动读取一个直接下载链接\n' +
        '.一键录卡 同意 —— 立即写入属性并生成速查卡\n' +
        '.一键录卡 确认 —— “同意”的兼容别名\n' +
        '.一键录卡 卡图 —— 补发最近识别的卡图，不写入角色属性\n' +
        '.角色卡评分 —— 让艾拉点评最近识别的角色卡\n\n' +
        '安全说明：上传文件只会进入候选列表；执行“导入”前，骰娘不会下载或读取内容。', [
          { label: '查看文件列表', data: '.一键录卡 列表' },
          { label: '导入最新文件', data: '.一键录卡 导入 最新' },
          { label: '背景故事评分', data: '.角色卡评分' }
        ]));
      return seal.ext.newCmdExecuteResult(true);
    }
    if (action === '列表' || action === '文件') {
      await showFileList(ctx, msg);
      return seal.ext.newCmdExecuteResult(true);
    }
    if (action === '导入' || action === '读取' || action === '选择') {
      const selector = String(cmdArgs.getArgN(2) || '').trim();
      await importCandidate(ctx, msg, selector);
      return seal.ext.newCmdExecuteResult(true);
    }
    if (action === '上传') {
      const url = String(cmdArgs.getArgN(2) || '').trim();
      if (!url) {
        seal.replyToSender(ctx, msg, '请提供 .xls/.xlsx/.xlsm 文件下载链接。');
      } else {
        const filename = decodeURIComponent(url.split('/').pop().split(/[?#]/)[0]) || 'upload.xlsx';
        await discover(ctx, msg, { filename: filename, url: url });
      }
      return seal.ext.newCmdExecuteResult(true);
    }

    if (action === '卡图' || action === '补发卡图') {
      const target = getPending(ctx, msg) || getLast(ctx, msg);
      if (!target) {
        seal.replyToSender(ctx, msg, '没有仍在有效期内的角色卡。请上传原表格后发送 .一键录卡 导入 最新，识别后再发送 .一键录卡 卡图；无需发送“同意”或“重录”。');
        return seal.ext.newCmdExecuteResult(true);
      }
      try {
        const data = await renderPortraitCard(ctx, msg, target.token);
        seal.replyToSender(ctx, msg,
          '角色卡：' + data.record.name + '\n' + cardImageMessages(ctx, msg, data) +
          officialQQButtonMarker(ctx, msg, [{ label: '角色卡评分', data: '.角色卡评分' }]));
      } catch (error) {
        seal.replyToSender(ctx, msg, '卡图获取失败：' + error.message + '\n若角色卡已过期，请重新上传原表格并执行 .一键录卡 导入 最新，识别后再发送 .一键录卡 卡图。');
      }
      return seal.ext.newCmdExecuteResult(true);
    }

    let pending = getPending(ctx, msg);
    if (!pending && action === '重录') pending = getLast(ctx, msg);
    if (!pending) {
      seal.replyToSender(ctx, msg, withOfficialQQButtons(ctx, msg,
        '没有已经读取并等待确认的人物卡。\n' +
        '发送 .一键录卡 列表 查看候选文件，再用 .一键录卡 导入 序号 主动读取。', [
          { label: '查看文件列表', data: '.一键录卡 列表' },
          { label: '导入最新文件', data: '.一键录卡 导入 最新' }
        ]));
      return seal.ext.newCmdExecuteResult(true);
    }
    if (pending.sealSystem === 'story') {
      seal.replyToSender(ctx, msg, withOfficialQQButtons(ctx, msg,
        '这张卡目前属于“仅背景故事评审”适配，不会写入海豹规则属性。\n' +
        "请回复 '.角色卡评分'，让艾拉细读角色的背景故事～", [
          { label: '背景故事评分', data: '.角色卡评分' }
        ]));
      return seal.ext.newCmdExecuteResult(true);
    }
    if (!systemMatches(ctx, pending.sealSystem)) {
      seal.replyToSender(ctx, msg, withOfficialQQButtons(ctx, msg, mismatchText(pending.sealSystem), [
        ruleSwitchButton(pending.sealSystem),
        { label: '同意录卡', data: '.一键录卡 同意' },
        { label: '背景故事评分', data: '.角色卡评分' }
      ]));
      return seal.ext.newCmdExecuteResult(true);
    }

    if (action === '同意' || action === '确认' || action === '重录') {
      try {
        const pokemonDestination = pending.sealSystem === 'pokemon' ? pokemonNativeCard(ctx) : null;
        const data = await renderPortraitCard(ctx, msg, pending.token);
        const imageMessages = cardImageMessages(ctx, msg, data);
        const count = data.record.seal_system === 'pokemon'
          ? applyPokemonRecord(ctx, msg, data.record, pokemonDestination && pokemonDestination.id)
          : applyRecord(ctx, data.record);
        const sharedRole = registerCharacterProfile(ctx, msg, data.character);
        setLast(ctx, msg, pending);
        clearPending(ctx, msg);
        const pokemonHint = data.record.seal_system === 'pokemon'
          ? '\n训练家、技能、宝可梦及招式已保存到当前宝可梦训练家存档。' +
            ((pokemonDestination && pokemonDestination.legacy)
              ? ''
              : '当前 .pc 旅伴角色卡【' + pokemonNativeCard(ctx).name + '】。') +
            '新角色请先 .pc new 角色名；切换用 .pc tag 角色名。\n发送 .宝可梦队伍 查看；.ra/.pm 技能检定；.宝可梦伤害 help 查看伤害骰。'
          : '';
        const portraitHint = data.setpic_portrait_saved
          ? '\n角色头像已同步到 .setpic 共用头像库，LogAI个人评分可直接使用。'
          : (data.portrait_archived && data.setpic_portrait_error
            ? '\n角色头像已保存，但同步到 .setpic 共用头像库失败；请检查后端头像目录配置。'
            : '');
        seal.replyToSender(
          ctx,
          msg,
          '录卡成功：' + data.record.name + '，已写入 ' + count + ' 项。' +
          pokemonHint +
          portraitHint +
          (sharedRole ? '\n已同步到跨平台角色档案；SealChat 的个人评分可直接读取这份设定。' : '\n未检测到“跨平台身份中心”，本次角色档案只保存在当前插件。') +
          '\n想听艾拉点评的话，回复 .角色卡评分\n' + imageMessages +
          officialQQButtonMarker(ctx, msg, [{ label: '角色卡评分', data: '.角色卡评分' }])
        );
      } catch (error) {
        seal.replyToSender(ctx, msg, '录卡失败，未清除待确认数据：' + error.message);
      }
      return seal.ext.newCmdExecuteResult(true);
    }

    const result = seal.ext.newCmdExecuteResult(true);
    result.showHelp = true;
    return result;
  };
  ext.cmdMap['一键录卡'] = cmd;

  const reviewCmd = seal.ext.newCmdItemInfo();
  reviewCmd.name = '角色卡评分';
  reviewCmd.help = '让艾拉只根据最近导入角色卡中的背景故事进行评审与评分';
  reviewCmd.solve = async (ctx, msg) => {
    if (!serviceOpenNow(ctx, msg)) {
      replySleeping(ctx, msg);
      return seal.ext.newCmdExecuteResult(true);
    }
    const target = getPending(ctx, msg) || getLast(ctx, msg);
    if (!target) {
      seal.replyToSender(ctx, msg,
        '艾拉歪着脑袋翻了翻口袋：咦，还没有读取人物卡呢？' +
        '请先发送 .一键录卡 列表，再用 .一键录卡 导入 序号 选择一张卡呀～');
      return seal.ext.newCmdExecuteResult(true);
    }
    const lockKey = (fishingUserIds(ctx, msg)[0] || 'unknown') + ':' + target.token;
    if (reviewLocks[lockKey]) {
      seal.replyToSender(ctx, msg, '这张角色卡正在接受艾拉评审，请稍等一下。');
      return seal.ext.newCmdExecuteResult(true);
    }
    const aiSettings = reviewAISettings();
    if (!aiSettings.ok) {
      seal.replyToSender(ctx, msg, aiSettings.error);
      return seal.ext.newCmdExecuteResult(true);
    }
    const billingAccount = reviewBillingPrecheck(ctx, msg);
    if (!billingAccount.ok) {
      seal.replyToSender(ctx, msg, billingAccount.error);
      return seal.ext.newCmdExecuteResult(true);
    }
    reviewLocks[lockKey] = true;
    seal.replyToSender(ctx, msg, '这次是预言系的魔法哦~艾拉正在仪式施法，请耐心等待，应该比十分钟要快一些吧……');
    try {
      const requestId = reviewRequestId(ctx, msg, target.token);
      const data = await api('/api/v1/review/' + target.token, {
        method: 'POST',
        body: JSON.stringify({ request_id: requestId, review_ai: aiSettings.value })
      });
      const review = data.review || {};
      const billing = data.billing || {};
      let billingNotice = '\n\n⚠️ 本次未成功调用AI，已使用默认评分且未扣宝可元。';
      if (billing.ai_used === true || review.review_source === 'ai') {
        const totalTokens = Math.max(0, Math.floor(Number(billing.total_tokens || review.total_tokens) || 0));
        const charge = Math.max(
          calculateReviewCharge(totalTokens),
          Math.floor(Number(billing.pokecoin_charge) || 0)
        );
        const settled = settleReviewCharge(billingAccount, requestId, charge, totalTokens);
        billingNotice = '\n\n本次AI评分消耗 ' + settled.totalTokens + ' Token，扣除 ' + settled.amount +
          ' 宝可元；当前余额 ' + settled.balance + ' 宝可元。' +
          (billing.usage_estimated ? '（接口未返回用量，Token为保守估算）' : '') +
          (settled.accountCount > 1 ? ' 已同步' + settled.accountCount + '个关联账户。' : '') +
          (settled.balance < 0 ? '余额已经为负，还清前无法再次评分。' : '');
      }
      const comment = String(review.ella_comment || '').replace(/^艾拉说：/, '');
      const text = '叮铃——妖精评审官艾拉读完了这段背景故事！\n' +
        '【艾拉的背景故事评审】\n' +
        '角色：' + (review.name || target.character) + '\n' +
        '人物清晰度：' + review.clarity_score + ' | 故事完整度：' + review.completeness_score + ' | 趣味与可玩性：' + review.interest_score + '\n' +
        '背景评分：' + review.total_score + '/100\n' +
        '结论：' + review.verdict + '\n\n' +
        '艾拉：' + comment + billingNotice;
      if (isOfficialQQ(ctx, msg) && isPublicHttpsImage(data.review_image_url)) {
        const reviewImage = cardImageMessages(ctx, msg, {
          image_url: data.review_image_url, image_sizes: [data.review_image_size]
        });
        seal.replyToSender(ctx, msg, text + '\n\n' + reviewImage +
          officialQQButtonMarker(ctx, msg, [{ label: '查看文件', data: '.一键录卡 列表' }]));
      } else {
        seal.replyToSender(ctx, msg, text);
        seal.replyToSender(ctx, msg, '[CQ:image,file=' + data.review_image_url + ',cache=0]');
      }
    } catch (error) {
      seal.replyToSender(ctx, msg, '艾拉的评审魔法打了个喷嚏：' + error.message + '。请重新导入人物卡再试一次吧。');
    } finally {
      delete reviewLocks[lockKey];
    }
    return seal.ext.newCmdExecuteResult(true);
  };
  ext.cmdMap['角色卡评分'] = reviewCmd;
})();
