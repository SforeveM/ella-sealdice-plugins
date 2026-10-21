// ==UserScript==
// @name         拆炸弹
// @author       WONS & Codex
// @version      1.0.0
// @description  六色剪线、随时收手、爆炸反向扣款，并与宝可梦钓鱼宝可元主账户联动
// @timestamp    2026/08/31
// @license      MIT
// ==/UserScript==

(function () {
  'use strict';

  var VERSION = '1.0.0';
  var EXT_NAME = 'ella-bomb-defusal';
  var FISHING_EXT_NAME = 'fishingSystemV2';
  var FISHING_STORAGE_SUFFIX = '_pokemon_fish_v1';
  var OFFICIAL_MD_MARKER = '[SealDice-OfficialQQ-WelcomeMarkdown]';
  var FIRST_REWARD = 40;
  var MAX_BUTTONS_PER_MESSAGE = 5;
  var WIRES = [
    { id: 'red', name: '红线', color: '#ef4444' },
    { id: 'blue', name: '蓝线', color: '#3b82f6' },
    { id: 'yellow', name: '黄线', color: '#facc15' },
    { id: 'green', name: '绿线', color: '#22c55e' },
    { id: 'purple', name: '紫线', color: '#a855f7' },
    { id: 'white', name: '白线', color: '#f8fafc' }
  ];

  var ext = seal.ext.find(EXT_NAME);
  if (!ext) {
    ext = seal.ext.new(EXT_NAME, 'WONS & Codex', VERSION);
    seal.ext.register(ext);
  }
  seal.ext.registerStringConfig(ext, '拆弹绘图后端地址', 'http://127.0.0.1:12152', '本地拆弹图片后端，不要以 / 结尾');
  seal.ext.registerStringConfig(ext, '拆弹后端API令牌', 'bomb-local', '必须与 BOMB_API_TOKEN 一致');
  seal.ext.registerStringConfig(ext, '每日可开始局数', '1', '每名玩家每个自然日可开始的拆弹局数，建议保持 1');
  seal.ext.registerBoolConfig(ext, '发送拆弹图片', true, '关闭后使用纯文字状态');

  function text(value) { return String(value === undefined || value === null ? '' : value); }
  function trim(value) { return text(value).trim(); }
  function now() { return Date.now(); }
  function todayKey() { return new Date(now() + 8 * 3600000).toISOString().slice(0, 10); }
  function randomId() { return now().toString(36) + Math.random().toString(36).slice(2, 10); }
  function dailyLimit() {
    var value = Math.trunc(Number(seal.ext.getStringConfig(ext, '每日可开始局数')) || 1);
    return Math.max(1, Math.min(20, value));
  }
  function userId(ctx, msg) {
    var values = [];
    try { if (seal.identity && typeof seal.identity.canonicalUserId === 'function') values.push(seal.identity.canonicalUserId(ctx, msg)); } catch (_e0) {}
    try { values.push(ctx && ctx.player && ctx.player.userId); } catch (_e1) {}
    try { values.push(msg && msg.sender && msg.sender.userId); } catch (_e2) {}
    try { values.push(ctx && ctx.userId); } catch (_e3) {}
    for (var i = 0; i < values.length; i += 1) if (trim(values[i])) return trim(values[i]);
    return 'unknown-user';
  }
  function userName(ctx, msg) {
    var values = [];
    try { values.push(ctx && ctx.player && ctx.player.name); } catch (_e1) {}
    try { values.push(msg && msg.sender && msg.sender.nickname); } catch (_e2) {}
    for (var i = 0; i < values.length; i += 1) if (trim(values[i])) return trim(values[i]).slice(0, 36);
    return '拆弹员';
  }
  function isOfficialQQ(ctx, msg) {
    var values = [];
    try { values.push(msg && msg.platform, msg && msg.sender && msg.sender.userId, msg && msg.groupId); } catch (_e1) {}
    try { values.push(ctx && ctx.player && ctx.player.userId, ctx && ctx.group && ctx.group.groupId, ctx && ctx.endPoint && ctx.endPoint.platform); } catch (_e2) {}
    return values.some(function (value) { return /^OPENQQ(?:CH)?(?:[-:]|$)/i.test(trim(value)); });
  }
  function marker(ctx, msg, buttons) {
    if (!isOfficialQQ(ctx, msg)) return '';
    var out = [], item, label, data;
    for (var i = 0; i < buttons.length && out.length < MAX_BUTTONS_PER_MESSAGE; i += 1) {
      item = buttons[i] || {};
      label = trim(item.label).replace(/[|;\[\]\r\n]/g, '').slice(0, 10);
      data = text(item.data).replace(/^\s+/, '');
      if (label && trim(data).charAt(0) === '.' && data.length <= 128 && !/[|;\[\]\r\n]/.test(data)) out.push(label + '|' + data + (item.send ? '|send' : ''));
    }
    return out.length ? '\n[SealDice-OfficialQQ-InputButtons:' + out.join(';') + ']' : '';
  }
  function reply(ctx, msg, content, buttons) {
    var body = text(content);
    if (isOfficialQQ(ctx, msg)) body = OFFICIAL_MD_MARKER + '\n' + body;
    seal.replyToSender(ctx, msg, body + marker(ctx, msg, buttons || []));
  }
  function replyPaged(ctx, msg, content, buttons) {
    var list = buttons || [];
    if (!isOfficialQQ(ctx, msg) || list.length <= MAX_BUTTONS_PER_MESSAGE) {
      reply(ctx, msg, content, list); return;
    }
    reply(ctx, msg, content, list.slice(0, MAX_BUTTONS_PER_MESSAGE));
    for (var index = MAX_BUTTONS_PER_MESSAGE; index < list.length; index += MAX_BUTTONS_PER_MESSAGE) {
      reply(ctx, msg, '其余可选线路：', list.slice(index, index + MAX_BUTTONS_PER_MESSAGE));
    }
  }
  function argsOf(cmdArgs, limit) {
    var result = [];
    for (var i = 1; i <= (limit || 12); i += 1) {
      var value = trim(cmdArgs.getArgN(i));
      if (!value) break;
      result.push(value);
    }
    return result;
  }
  function readJson(key) { try { var raw = ext.storageGet(key); return raw ? JSON.parse(raw) : null; } catch (_error) { return null; } }
  function writeJson(key, value) { ext.storageSet(key, value ? JSON.stringify(value) : ''); }
  function profileKey(id) { return 'profile:' + id; }
  function loadProfile(id) {
    var profile = readJson(profileKey(id));
    if (!profile || typeof profile !== 'object') profile = { version: 1, createdAt: now(), history: [] };
    if (!Array.isArray(profile.history)) profile.history = [];
    if (profile.dailyDay !== todayKey()) { profile.dailyDay = todayKey(); profile.startsToday = 0; }
    profile.startsToday = Math.max(0, Math.trunc(Number(profile.startsToday) || 0));
    return profile;
  }
  function saveProfile(id, profile) { profile.updatedAt = now(); writeJson(profileKey(id), profile); }

  function fishingUserIds(ctx, msg) {
    var result = [];
    function add(value) {
      var normalized = trim(value), colon, shortId;
      if (!normalized) return;
      if (result.indexOf(normalized) < 0) result.push(normalized);
      colon = normalized.lastIndexOf(':');
      if (colon >= 0) {
        shortId = trim(normalized.slice(colon + 1));
        if (shortId && result.indexOf(shortId) < 0) result.push(shortId);
      }
    }
    try { add(ctx && ctx.player && ctx.player.userId); } catch (_e1) {}
    try { add(msg && msg.sender && msg.sender.userId); } catch (_e2) {}
    try { add(ctx && ctx.userId); } catch (_e3) {}
    try { if (seal.identity && typeof seal.identity.canonicalUserId === 'function') add(seal.identity.canonicalUserId(ctx, msg)); } catch (_e4) {}
    return result;
  }
  function fishingExt() {
    var fishing = null;
    try { fishing = seal.ext.find(FISHING_EXT_NAME); } catch (_error) {}
    if (!fishing || typeof fishing.storageGet !== 'function' || typeof fishing.storageSet !== 'function') throw new Error('没有找到宝可梦生态钓鱼插件，无法读写宝可元。');
    return fishing;
  }
  function parseWallet(fishing, key) {
    var data = {}, raw = '';
    try { raw = fishing.storageGet(key); if (raw) data = JSON.parse(raw); } catch (_error) { throw new Error('宝可元账户读取失败。'); }
    if (!data || typeof data !== 'object') data = {};
    data.coins = Math.trunc(Number(data.coins) || 0);
    if (!Array.isArray(data.ellaBombDefusalTransactions)) data.ellaBombDefusalTransactions = [];
    return data;
  }
  function locateWallet(ctx, msg) {
    var fishing = fishingExt(), ids = fishingUserIds(ctx, msg), fallback = null, raw, key;
    for (var i = 0; i < ids.length; i += 1) {
      key = ids[i] + FISHING_STORAGE_SUFFIX;
      try { raw = fishing.storageGet(key); } catch (_error) { continue; }
      if (raw) return { ext: fishing, key: key, data: parseWallet(fishing, key) };
      if (!fallback) fallback = key;
    }
    key = fallback || userId(ctx, msg) + FISHING_STORAGE_SUFFIX;
    return { ext: fishing, key: key, data: parseWallet(fishing, key) };
  }
  function walletByKey(key) { var fishing = fishingExt(); return { ext: fishing, key: key, data: parseWallet(fishing, key) }; }
  function applyWallet(account, delta, transactionId) {
    var fresh = parseWallet(account.ext, account.key), ledger = fresh.ellaBombDefusalTransactions;
    for (var i = 0; i < ledger.length; i += 1) if (ledger[i] && ledger[i].id === transactionId) return { already: true, balance: fresh.coins };
    fresh.coins += Math.trunc(Number(delta) || 0);
    fresh.isDebtor = fresh.coins < 0;
    fresh.debt = fresh.isDebtor ? Math.abs(fresh.coins) : 0;
    ledger.push({ id: transactionId, delta: Math.trunc(Number(delta) || 0), at: now(), reason: 'bomb-defusal' });
    if (ledger.length > 100) ledger.splice(0, ledger.length - 100);
    account.ext.storageSet(account.key, JSON.stringify(fresh));
    return { already: false, balance: fresh.coins };
  }

  function resolveWire(value) {
    var wanted = trim(value).replace(/\s+/g, '').toLowerCase();
    for (var i = 0; i < WIRES.length; i += 1) {
      if (wanted === WIRES[i].id || wanted === WIRES[i].name || wanted === WIRES[i].name.charAt(0)) return WIRES[i];
    }
    return null;
  }
  function currentSession(profile) { return profile.active && profile.active.status === 'active' ? profile.active : null; }
  function visibleSession(profile) { return currentSession(profile) || profile.lastSession || null; }
  function rewardForSafeCuts(count) { return count > 0 ? FIRST_REWARD * Math.pow(2, count - 1) : 0; }
  function wireButtons(session) {
    if (!session || session.status !== 'active') return [
      { label: '查看规则', data: '.拆弹 规则', send: true },
      { label: '查看状态', data: '.拆弹 状态', send: true }
    ];
    var buttons = [{ label: '立即收手', data: '.拆弹 操作 ' + session.id + ' cashout', send: true }];
    WIRES.forEach(function (wire) {
      if (session.cut.indexOf(wire.id) < 0) buttons.push({ label: '剪' + wire.name, data: '.拆弹 操作 ' + session.id + ' cut ' + wire.id, send: true });
    });
    return buttons;
  }
  function statusLabel(session) {
    if (!session) return '尚未开始';
    if (session.status === 'active') return '拆弹进行中';
    if (session.status === 'cashed') return '安全收手';
    return '炸弹爆炸';
  }
  function plainState(session, balance) {
    if (!session) return '【拆炸弹】当前没有进行中的拆弹。\n发送 `.拆弹 开始` 创建今日拆弹局。';
    var cutNames = session.cut.map(function (id) { return resolveWire(id).name; });
    var lines = ['【拆炸弹】' + statusLabel(session), '安全剪线：' + session.safeCount + '/5', '已剪：' + (cutNames.length ? cutNames.join('、') : '无')];
    if (session.status === 'active') {
      lines.push('当前可收手奖励：' + session.pendingReward + '宝可元');
      lines.push('继续失误将清空本局奖励，并额外扣除' + session.pendingReward + '宝可元。');
      lines.push('可直接发送 `.拆弹 剪 红/蓝/黄/绿/紫/白`，或 `.拆弹 收手`。');
    } else if (session.status === 'cashed') {
      lines.push('本局已结算：+' + session.payout + '宝可元。');
      lines.push('错误线路：' + resolveWire(session.bombColor).name + '。');
    } else {
      lines.push('剪中了' + resolveWire(session.bombColor).name + '，本局奖励归零，额外扣除' + session.penalty + '宝可元。');
    }
    lines.push('当前宝可元：' + balance);
    return lines.join('\n');
  }
  function backendBase() { return trim(seal.ext.getStringConfig(ext, '拆弹绘图后端地址')).replace(/\/(?:api\/v1\/render|health)\/?$/i, '').replace(/\/+$/, ''); }
  function renderPayload(profile, session, balance) {
    return {
      kind: 'bomb', version: VERSION, player_name: profile.playerName || '拆弹员', status: session ? session.status : 'idle',
      status_label: statusLabel(session), safe_count: session ? session.safeCount : 0, pending_reward: session ? session.pendingReward : 0,
      payout: session ? Number(session.payout || 0) : 0, penalty: session ? Number(session.penalty || 0) : 0,
      balance: balance, revealed_color: session && session.status !== 'active' ? session.bombColor : '',
      wires: WIRES.map(function (wire) { return { id: wire.id, name: wire.name, color: wire.color, cut: !!(session && session.cut.indexOf(wire.id) >= 0) }; })
    };
  }
  function renderState(ctx, msg, profile, notice) {
    var session = visibleSession(profile), account = profile.walletKey ? walletByKey(profile.walletKey) : locateWallet(ctx, msg), balance = account.data.coins;
    profile.walletKey = account.key;
    var fallback = (notice ? notice + '\n' : '') + plainState(session, balance), buttons = wireButtons(session);
    if (!seal.ext.getBoolConfig(ext, '发送拆弹图片') || typeof fetch !== 'function' || !backendBase()) { replyPaged(ctx, msg, fallback, buttons); return; }
    var headers = { 'Content-Type': 'application/json' }, token = trim(seal.ext.getStringConfig(ext, '拆弹后端API令牌'));
    if (token) headers['X-API-Key'] = token;
    return fetch(backendBase() + '/api/v1/render', { method: 'POST', headers: headers, body: JSON.stringify(renderPayload(profile, session, balance)) })
      .then(function (response) { if (!response.ok) throw new Error('HTTP ' + response.status); return response.json(); })
      .then(function (data) {
        if (!data || !data.ok || (!data.image_url && !data.image_path)) throw new Error('绘图后端没有返回图片');
        if (isOfficialQQ(ctx, msg) && /^https:\/\//i.test(trim(data.image_url))) {
          replyPaged(ctx, msg, (notice ? notice + '\n\n' : '') + '![拆炸弹面板#' + Number(data.image_width || 1400) + 'px #' + Number(data.image_height || 980) + 'px](' + data.image_url + ')', buttons); return;
        }
        if (data.image_path) seal.replyToSender(ctx, msg, '[CQ:image,file=' + text(data.image_path).replace(/\\/g, '/') + ',cache=0]');
        replyPaged(ctx, msg, fallback, buttons);
      }).catch(function (error) { replyPaged(ctx, msg, fallback + '\n（拆弹图片暂不可用：' + text(error && error.message || error).slice(0, 80) + '）', buttons); });
  }

  function startGame(ctx, msg) {
    var id = userId(ctx, msg), profile = loadProfile(id), active = currentSession(profile);
    if (active) { renderState(ctx, msg, profile, '你已有一局拆弹正在进行。'); return; }
    if (profile.startsToday >= dailyLimit()) throw new Error('你今天已经完成过拆弹，明天再来吧。');
    var account = locateWallet(ctx, msg), bomb = WIRES[Math.floor(Math.random() * WIRES.length)];
    profile.playerName = userName(ctx, msg);
    profile.walletKey = account.key;
    profile.startsToday += 1;
    profile.active = {
      id: randomId(), status: 'active', createdAt: now(), bombColor: bomb.id, cut: [], safeCount: 0,
      pendingReward: 0, payout: 0, penalty: 0, walletKey: account.key
    };
    saveProfile(id, profile);
    renderState(ctx, msg, profile, '计时器已经启动。六根线中只有一根会引爆炸弹。');
  }
  function requireActive(profile, sessionId) {
    var session = currentSession(profile);
    if (!session) throw new Error('当前没有进行中的拆弹。');
    if (sessionId && session.id !== sessionId) throw new Error('这个按钮属于已经失效的拆弹局，请刷新状态。');
    return session;
  }
  function archiveSession(profile, session) {
    profile.lastSession = JSON.parse(JSON.stringify(session));
    profile.history.push({ id: session.id, status: session.status, safeCount: session.safeCount, payout: session.payout || 0, penalty: session.penalty || 0, at: now() });
    if (profile.history.length > 30) profile.history.splice(0, profile.history.length - 30);
    profile.active = null;
  }
  function cutWire(ctx, msg, sessionId, wireInput) {
    var id = userId(ctx, msg), profile = loadProfile(id), session = requireActive(profile, sessionId), wire = resolveWire(wireInput);
    if (!wire) throw new Error('没有这根线，请选择红、蓝、黄、绿、紫、白之一。');
    if (session.cut.indexOf(wire.id) >= 0) throw new Error(wire.name + '已经被剪断了。');
    if (wire.id === session.bombColor) {
      var penalty = Math.max(0, Math.trunc(Number(session.pendingReward) || 0));
      var account = walletByKey(session.walletKey || profile.walletKey), result = applyWallet(account, -penalty, 'bomb-explode:' + session.id);
      session.status = 'exploded'; session.penalty = penalty; session.payout = 0; session.explodedAt = now();
      archiveSession(profile, session); saveProfile(id, profile);
      renderState(ctx, msg, profile, '💥 炸弹爆炸！本局奖励全部消失，并额外扣除' + penalty + '宝可元；当前余额' + result.balance + '。'); return;
    }
    session.cut.push(wire.id);
    session.safeCount += 1;
    session.pendingReward = rewardForSafeCuts(session.safeCount);
    saveProfile(id, profile);
    renderState(ctx, msg, profile, '剪断' + wire.name + '，安全！现在收手可获得' + session.pendingReward + '宝可元。');
  }
  function cashOut(ctx, msg, sessionId) {
    var id = userId(ctx, msg), profile = loadProfile(id), session = requireActive(profile, sessionId);
    var payout = Math.max(0, Math.trunc(Number(session.pendingReward) || 0));
    var account = walletByKey(session.walletKey || profile.walletKey), result = applyWallet(account, payout, 'bomb-cashout:' + session.id);
    session.status = 'cashed'; session.payout = payout; session.penalty = 0; session.cashedAt = now();
    archiveSession(profile, session); saveProfile(id, profile);
    renderState(ctx, msg, profile, '你及时收手，本局获得' + payout + '宝可元；当前余额' + result.balance + '。');
  }
  function showMenu(ctx, msg) {
    var profile = loadProfile(userId(ctx, msg)), active = currentSession(profile);
    if (active) { renderState(ctx, msg, profile, '你的拆弹还没有结束。'); return; }
    reply(ctx, msg,
      '## 💣 六色拆弹\n六根不同颜色的线中藏着一根错误线路。第一根安全线价值40宝可元，此后奖励依次翻倍。你可以随时收手；若引爆炸弹，本局奖励归零，还会从钓鱼宝可元账户额外扣除当前累计值。\n\n每人每天可开始' + dailyLimit() + '局。',
      [{ label: '开始拆弹', data: '.拆弹 开始', send: true }, { label: '查看规则', data: '.拆弹 规则', send: true }, { label: '查看状态', data: '.拆弹 状态', send: true }]);
  }
  function showRules(ctx, msg) {
    reply(ctx, msg,
      '## 💣 拆炸弹规则\n- 6根线中固定有1根错误线，位置每局随机。\n- 连续安全剪线后的可结算奖励：40、80、160、320、640宝可元。\n- 可随时点击“立即收手”，奖励才会写入钓鱼主账户。\n- 剪中错误线：未结算奖励归零，并从账户额外扣除同等金额；余额可以变成负数。\n- 每人每天默认只能开始1局，未结束的局可以继续。\n- 旧按钮、重复按钮和他人的按钮不能重复结算。',
      [{ label: '开始拆弹', data: '.拆弹 开始', send: true }, { label: '返回状态', data: '.拆弹 状态', send: true }]);
  }
  function resetForTest(ctx, msg) {
    if (Number(ctx && ctx.privilegeLevel || 0) < 100) throw new Error('只有骰主可以重置拆弹测试次数。');
    var id = userId(ctx, msg), profile = loadProfile(id);
    profile.startsToday = 0; profile.active = null; profile.lastSession = null; saveProfile(id, profile);
    reply(ctx, msg, '拆弹测试状态已经重置；宝可元账户没有修改。', [{ label: '开始拆弹', data: '.拆弹 开始', send: true }]);
  }

  function makeCommand(name) {
    var command = seal.ext.newCmdItemInfo();
    command.name = name;
    command.help = '.拆弹 [开始|状态|规则|剪 <颜色>|收手]';
    command.allowDelegate = true;
    command.solve = function (ctx, msg, cmdArgs) {
      try {
        var args = argsOf(cmdArgs), op = trim(args[0]);
        if (!op || op === '菜单' || op === 'help' || op === '帮助') { showMenu(ctx, msg); return seal.ext.newCmdExecuteResult(true); }
        if (op === '开始') { startGame(ctx, msg); return seal.ext.newCmdExecuteResult(true); }
        if (op === '规则') { showRules(ctx, msg); return seal.ext.newCmdExecuteResult(true); }
        if (op === '状态' || op === '刷新') { var profile = loadProfile(userId(ctx, msg)); renderState(ctx, msg, profile, ''); return seal.ext.newCmdExecuteResult(true); }
        if (op === '剪') { var cuttingProfile = loadProfile(userId(ctx, msg)), cuttingSession = requireActive(cuttingProfile, ''); cutWire(ctx, msg, cuttingSession.id, args[1]); return seal.ext.newCmdExecuteResult(true); }
        if (op === '收手') { var cashProfile = loadProfile(userId(ctx, msg)), cashSession = requireActive(cashProfile, ''); cashOut(ctx, msg, cashSession.id); return seal.ext.newCmdExecuteResult(true); }
        if (op === '操作') {
          if (args[2] === 'cut') cutWire(ctx, msg, args[1], args[3]);
          else if (args[2] === 'cashout') cashOut(ctx, msg, args[1]);
          else throw new Error('无效的拆弹按钮。');
          return seal.ext.newCmdExecuteResult(true);
        }
        if (op === '测试重置') { resetForTest(ctx, msg); return seal.ext.newCmdExecuteResult(true); }
        throw new Error('未知指令。发送 `.拆弹` 查看菜单。');
      } catch (error) {
        reply(ctx, msg, '拆弹操作失败：' + text(error && error.message || error), [{ label: '刷新状态', data: '.拆弹 状态', send: true }, { label: '查看规则', data: '.拆弹 规则', send: true }]);
        return seal.ext.newCmdExecuteResult(true);
      }
    };
    return command;
  }

  var command = makeCommand('拆弹');
  ext.cmdMap['拆弹'] = command;
  ext.cmdMap['拆炸弹'] = command;
  ext.cmdMap['bomb'] = command;

  if (typeof globalThis !== 'undefined') {
    globalThis.__ELLA_BOMB_DEFUSAL_TEST__ = {
      VERSION: VERSION, WIRES: WIRES, FIRST_REWARD: FIRST_REWARD,
      loadProfile: loadProfile, saveProfile: saveProfile, rewardForSafeCuts: rewardForSafeCuts,
      resolveWire: resolveWire, applyWallet: applyWallet, locateWallet: locateWallet,
      startGame: startGame, cutWire: cutWire, cashOut: cashOut, visibleSession: visibleSession
    };
  }
})();
