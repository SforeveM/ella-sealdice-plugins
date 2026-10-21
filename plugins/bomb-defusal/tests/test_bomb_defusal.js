const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const pluginStorage = new Map();
const fishingStorage = new Map();
const replies = [];
const extensions = new Map();
const fishing = {
  storageGet: key => fishingStorage.get(key) || '',
  storageSet: (key, value) => fishingStorage.set(key, value),
};
extensions.set('fishingSystemV2', fishing);
const seal = {
  identity: { canonicalUserId: ctx => ctx.player.userId },
  ext: {
    find: name => extensions.get(name) || null,
    new: (name, author, version) => ({ name, author, version, cmdMap: {}, configs: {}, storageGet: key => pluginStorage.get(key) || '', storageSet: (key, value) => pluginStorage.set(key, value) }),
    register: extension => extensions.set(extension.name, extension),
    registerStringConfig: (extension, key, value) => { if (!(key in extension.configs)) extension.configs[key] = value; },
    registerBoolConfig: (extension, key, value) => { if (!(key in extension.configs)) extension.configs[key] = value; },
    getStringConfig: (extension, key) => extension.configs[key],
    getBoolConfig: (extension, key) => extension.configs[key],
    newCmdItemInfo: () => ({}),
    newCmdExecuteResult: ok => ({ ok }),
  },
  replyToSender: (_ctx, _msg, value) => replies.push(String(value)),
};
const context = { seal, console, JSON, Date, Math, Promise, setTimeout, clearTimeout };
context.globalThis = context;
vm.createContext(context);
const pluginPath = path.join(__dirname, '..', 'sealdice', 'BombDefusalGame_v1.0.0.js');
vm.runInContext(fs.readFileSync(pluginPath, 'utf8'), context, { filename: pluginPath });
const extension = extensions.get('ella-bomb-defusal');
const test = context.__ELLA_BOMB_DEFUSAL_TEST__;

function ctx(id, name, privilege = 0) {
  return { player: { userId: `OpenQQ:1000000000-${id}`, name }, group: { groupId: 'OpenQQ-Group:1000000000-BOMB' }, endPoint: { platform: 'OPENQQ' }, privilegeLevel: privilege };
}
function msg(context) { return { platform: 'OPENQQ', groupId: context.group.groupId, sender: { userId: context.player.userId, nickname: context.player.name } }; }
function args(values) { return { getArgN: index => values[index - 1] || '' }; }
function run(values, context, alias = '拆弹') { extension.cmdMap[alias].solve(context, msg(context), args(values)); return replies[replies.length - 1] || ''; }
function walletKey(context) { return `${context.player.userId}_pokemon_fish_v1`; }
function setWallet(context, coins) { fishingStorage.set(walletKey(context), JSON.stringify({ coins })); }
function wallet(context) { return JSON.parse(fishingStorage.get(walletKey(context))); }
function profile(context) { return test.loadProfile(context.player.userId); }

assert.strictEqual(test.VERSION, '1.0.0');
assert.strictEqual(test.WIRES.length, 6);
assert.deepStrictEqual(Array.from(test.WIRES, wire => wire.id), ['red', 'blue', 'yellow', 'green', 'purple', 'white']);
assert.strictEqual(test.rewardForSafeCuts(0), 0);
assert.strictEqual(test.rewardForSafeCuts(1), 40);
assert.strictEqual(test.rewardForSafeCuts(2), 80);
assert.strictEqual(test.rewardForSafeCuts(3), 160);
assert.strictEqual(test.rewardForSafeCuts(4), 320);
assert.strictEqual(test.rewardForSafeCuts(5), 640);
assert.strictEqual(test.resolveWire('红').id, 'red');
assert.strictEqual(test.resolveWire('蓝线').id, 'blue');
assert.strictEqual(extension.cmdMap['拆炸弹'], extension.cmdMap['拆弹']);
assert.strictEqual(extension.cmdMap.bomb, extension.cmdMap['拆弹']);

const expectedValues = [];
for (let target = 1; target <= 5; target += 1) {
  const survivalReward = (6 - target) / 6 * test.rewardForSafeCuts(target);
  let expectedPenalty = 0;
  for (let bombPosition = 1; bombPosition <= target; bombPosition += 1) expectedPenalty += test.rewardForSafeCuts(bombPosition - 1) / 6;
  expectedValues.push(survivalReward - expectedPenalty);
}
assert.ok(Math.abs(expectedValues[2] - 60) < 1e-9);
assert.ok(Math.abs(expectedValues[3] - 60) < 1e-9);
assert.ok(expectedValues[4] < 7);

const player = ctx('PLAYER', 'WONS');
setWallet(player, 1000);
run(['开始'], player);
let current = profile(player);
assert.ok(current.active && current.active.status === 'active');
assert.strictEqual(current.startsToday, 1);
assert.strictEqual(wallet(player).coins, 1000, 'starting a round must not change Pokecoins');

const startMessages = replies.slice(-2).join('\n');
assert.ok(startMessages.includes('立即收手|.拆弹 操作'));
assert.ok(test.WIRES.every(wire => startMessages.includes(`剪${wire.name}|.拆弹 操作`)), 'all six wire buttons must be present across the paged button messages');
for (const message of replies) {
  const match = message.match(/\[SealDice-OfficialQQ-InputButtons:([^\]]+)\]/);
  if (match) assert.ok(match[1].split(';').length <= 5, 'each Official QQ bubble must contain at most five buttons');
}

const safeWire = test.WIRES.find(wire => wire.id !== current.active.bombColor);
run(['操作', current.active.id, 'cut', safeWire.id], player);
current = profile(player);
assert.strictEqual(current.active.safeCount, 1);
assert.strictEqual(current.active.pendingReward, 40);
assert.strictEqual(wallet(player).coins, 1000, 'safe cuts remain unbanked until cashout');
const firstSessionId = current.active.id;
run(['操作', firstSessionId, 'cashout'], player);
assert.strictEqual(wallet(player).coins, 1040);
assert.strictEqual(profile(player).active, null);
assert.strictEqual(profile(player).lastSession.status, 'cashed');
run(['操作', firstSessionId, 'cashout'], player);
assert.ok(replies.pop().includes('当前没有进行中的拆弹'));
assert.strictEqual(wallet(player).coins, 1040, 'a replayed cashout button must not pay twice');
run(['开始'], player);
assert.ok(replies.pop().includes('今天已经完成过拆弹'));

const owner = ctx('OWNER', '骰主', 100);
setWallet(owner, 1000);
run(['测试重置'], owner);
run(['开始'], owner);
let ownerProfile = profile(owner);
ownerProfile.active.bombColor = 'red';
test.saveProfile(owner.player.userId, ownerProfile);
run(['剪', '蓝'], owner);
run(['剪', '绿'], owner);
assert.strictEqual(profile(owner).active.pendingReward, 80);
run(['剪', '红'], owner);
assert.strictEqual(wallet(owner).coins, 920, 'explosion must deduct the current unbanked reward');
assert.strictEqual(profile(owner).lastSession.penalty, 80);
assert.strictEqual(profile(owner).lastSession.payout, 0);

run(['测试重置'], owner);
setWallet(owner, 10);
run(['开始'], owner);
ownerProfile = profile(owner);
ownerProfile.active.bombColor = 'red';
test.saveProfile(owner.player.userId, ownerProfile);
run(['剪', '蓝'], owner);
run(['剪', '红'], owner);
assert.strictEqual(wallet(owner).coins, -30, 'explosion penalties may make the shared wallet negative');
assert.strictEqual(wallet(owner).isDebtor, true);
assert.strictEqual(wallet(owner).debt, 30);

const outsider = ctx('OUTSIDER', '路人');
setWallet(outsider, 500);
run(['操作', firstSessionId, 'cut', 'red'], outsider);
assert.strictEqual(wallet(outsider).coins, 500, 'another player cannot use an old foreign session button');

const account = { ext: fishing, key: walletKey(outsider) };
const once = test.applyWallet(account, 40, 'idempotency-probe');
const twice = test.applyWallet(account, 40, 'idempotency-probe');
assert.strictEqual(twice.already, true);
assert.strictEqual(twice.balance, once.balance);
assert.strictEqual(wallet(outsider).coins, 540);

console.log('Bomb defusal expected values:', expectedValues.map(value => Number(value.toFixed(2))).join('/'));
console.log('Bomb defusal plugin tests passed.');
