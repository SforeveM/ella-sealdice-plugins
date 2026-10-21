const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'sealdice', '一键录卡.js'), 'utf8');
const marker = '[SealDice-OfficialQQ-WelcomeMarkdown]';
const buttons = '\n[SealDice-OfficialQQ-InputButtons:角色卡评分|.角色卡评分]';
const official = { platform: 'OpenQQ', groupId: 'OpenQQ-Group:test', sender: { userId: 'OpenQQ:owner' } };
const ctx = { group: { groupId: official.groupId }, player: { userId: official.sender.userId } };
const scope = official.groupId + '|' + official.sender.userId;

function fixture() {
  const storage = new Map();
  const configs = new Map();
  const replies = [];
  const requests = [];
  let registered;
  let response;
  let failure;
  const sandbox = {
    console, Date, setTimeout,
    seal: {
      ext: {
        find: () => null,
        new: (name, author, version) => ({name, author, version, cmdMap: {},
          storageGet: key => storage.get(key) || '', storageSet: (key, value) => storage.set(key, value)}),
        register: ext => { registered = ext; },
        registerStringConfig: (_, key, value) => configs.set(key, value),
        registerIntConfig: (_, key, value) => configs.set(key, value),
        getStringConfig: (_, key) => configs.get(key),
        getIntConfig: (_, key) => configs.get(key),
        newCmdItemInfo: () => ({}), newCmdExecuteResult: () => ({matched: true}),
      },
      replyToSender: (_, __, text) => replies.push(text),
      vars: {
        intSet: () => { throw new Error('resend must not write attributes'); },
        strSet: () => { throw new Error('resend must not write character strings'); },
        strGet: () => { throw new Error('resend must not require the active rule to match'); },
      },
      setPlayerGroupCard: () => { throw new Error('resend must not rename the player'); },
    },
    fetch: async (url, options) => {
      requests.push({url, options});
      if (failure) throw new Error(failure);
      return {ok: true, json: async () => response};
    },
  };
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'globalThis.testImages = cardImageMessages;})();'), sandbox);
  return {storage, replies, requests, configs, registered, sandbox,
    response: data => { response = data; }, failure: text => { failure = text; }};
}

function renderResult(count) {
  const length = count > 12 ? 2 : count + 1;
  return {ok: true, record: {name: '卜卜鸟', seal_system: 'pokemon'},
    image_urls: Array.from({length}, (_, i) => 'https://autocard-api.example.com/cards/F_btWJ0B7xScVMpdRFjBNDVHbPPQOWN3' + (i ? '-pokemon-' + i : '') + '.png'),
    image_sizes: Array.from({length}, (_, i) => ({width: 1600, height: i ? 2400 : 1605}))};
}

// Reproduce the deployed core's pre-Markdown boundary from utils/split_text.go
// and platform_adapter_official_qq.go: UTF-8 bytes, blank-line preference,
// trusted-card allowance, then keyboard Markdown on only the final page.
function coreOutgoing(text) {
  const forced = text.includes(marker);
  const keyboard = text.includes('[SealDice-OfficialQQ-InputButtons:');
  text = text.split(marker).join('').replace(/\[SealDice-OfficialQQ-InputButtons:[^\]]*\]/g, '').trim();
  if (forced && Buffer.byteLength(text) <= 4000) return [{markdown: true, text}];
  const pages = [];
  while (Buffer.byteLength(text) > 900) {
    let bytes = 0;
    let split = 0;
    for (const c of text) {
      bytes += Buffer.byteLength(c);
      split += c.length;
      if (bytes >= 900) break;
    }
    const prefix = text.slice(0, split);
    const blank = /\n{2,}/.exec(prefix);
    let consumed = split;
    if (blank) { split = blank.index; consumed = split + blank[0].length; }
    else if (prefix.lastIndexOf('\n') >= 0) { split = prefix.lastIndexOf('\n'); consumed = split + 1; }
    pages.push(text.slice(0, split));
    text = text.slice(consumed);
  }
  if (text.trim()) pages.push(text);
  return pages.map((text, i) => ({text, markdown: forced || (keyboard && i === pages.length - 1)}));
}

async function main() {
  const f = fixture();
  const intro = '录卡成功：卜卜鸟，已写入 26 项。\n宝可梦队伍与招式也已保存。发送 .宝可梦队伍 查看；发送 .宝可梦伤害 help 学习命中/伤害骰。\n角色头像已同步到 .setpic 共用头像库，LogAI个人评分可直接使用。\n已同步到跨平台角色档案；SealChat 的个人评分可直接读取这份设定。\n想听艾拉点评的话，回复 .角色卡评分\n';
  const wire = intro + f.sandbox.testImages(ctx, official, renderResult(5)) + buttons;
  const legacy = coreOutgoing(wire.replace(marker + '\n', ''));
  assert(legacy.length > 1, 'fixture must cross the core split boundary');
  assert(legacy.some(page => !page.markdown && page.text.includes('![角色卡1')), 'reproduce trainer image sent as literal text');
  assert(legacy[legacy.length - 1].markdown, 'reproduce visible Pokemon on the keyboard page');
  const reports = [];
  for (const count of [0, 1, 4, 5, 12, 13, 25]) {
    const data = renderResult(count);
    const pages = coreOutgoing(intro + f.sandbox.testImages(ctx, official, data) + buttons);
    assert.equal(pages.length, 1, count + ' companions must not consume multiple reply quotas');
    assert(pages[0].markdown);
    assert(pages[0].text.includes('![角色卡1 #1600px #1605px]'));
    for (const url of data.image_urls) assert(pages[0].text.includes('](' + url + ')'));
    reports.push({companions: count, images: data.image_urls.length, bytes: Buffer.byteLength(pages[0].text), pages: pages.length});
  }
  const normal = f.sandbox.testImages({}, {platform: 'QQ', sender: {userId: 'QQ:123'}}, renderResult(5));
  assert(!normal.includes(marker));
  assert.equal((normal.match(/\[CQ:image/g) || []).length, 6);
  assert.throws(() => f.sandbox.testImages(ctx, official, {image_url: 'http://127.0.0.1/private.png'}), /公网 HTTPS/);
  assert.throws(() => f.sandbox.testImages(ctx, official, {}), /没有返回/);
  const legacyOne = f.sandbox.testImages(ctx, official, {image_url: 'https://autocard-api.example.com/cards/old.png', image_urls: []});
  assert(coreOutgoing(legacyOne + buttons)[0].markdown);

  const last = JSON.stringify({[scope]: {token: 'last-token', createdAt: Date.now(), sealSystem: 'pokemon'}});
  f.storage.set('last_cards', last);
  f.response(renderResult(5));
  await f.registered.cmdMap['一键录卡'].solve(ctx, official, {getArgN: n => n === 1 ? '卡图' : ''});
  assert.equal(f.requests.length, 1);
  assert(f.requests[0].url.endsWith('/api/v1/render/last-token'));
  assert.deepEqual(JSON.parse(f.requests[0].options.body), {owner_ids: [official.sender.userId]});
  assert.equal(f.replies.length, 1);
  assert(f.replies[0].includes('角色卡：卜卜鸟'));
  assert(coreOutgoing(f.replies[0])[0].markdown);
  assert.equal(f.storage.get('last_cards'), last);
  assert(!f.storage.has('pokemon_rosters'));

  const pending = JSON.stringify({[scope]: {token: 'pending-token', createdAt: Date.now(), sealSystem: 'pokemon'}});
  f.storage.set('pending_cards', pending);
  await f.registered.cmdMap['一键录卡'].solve(ctx, official, {getArgN: () => '补发卡图'});
  assert(f.requests.at(-1).url.endsWith('/api/v1/render/pending-token'));
  assert.equal(f.storage.get('pending_cards'), pending, 'viewing an unconfirmed card must not confirm or clear it');
  f.failure('文件已过期');
  await f.registered.cmdMap['一键录卡'].solve(ctx, official, {getArgN: () => '卡图'});
  assert(f.replies.at(-1).includes('重新上传原表格'));
  assert.equal(f.storage.get('pending_cards'), pending);

  const empty = fixture();
  await empty.registered.cmdMap['一键录卡'].solve(ctx, official, {getArgN: () => '卡图'});
  assert.equal(empty.requests.length, 0);
  assert(empty.replies[0].includes('无需发送“同意”或“重录”'));
  const differentOwner = { ...ctx, player: {userId: 'OpenQQ:someone-else'} };
  const differentMsg = {...official, sender: {userId: differentOwner.player.userId}};
  await f.registered.cmdMap['一键录卡'].solve(differentOwner, differentMsg, {getArgN: () => '卡图'});
  assert(f.replies.at(-1).includes('没有仍在有效期'));
  console.log('PASS trainer Markdown regression, complete Pokemon images, OneBot compatibility, resend isolation and no attribute writes');
  console.log(JSON.stringify(reports, null, 2));
}
main().catch(error => { console.error(error); process.exit(1); });
