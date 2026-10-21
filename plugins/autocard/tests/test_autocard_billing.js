const fs = require('fs');
const vm = require('vm');

const pluginStorage = new Map();
const fishingStorage = new Map();
const replies = [];
const configs = {
  '服务地址': 'http://127.0.0.1:8765',
  'API令牌': 'secret',
  'AI评分API地址': 'https://ai.example.com/v1',
  'AI评分API密钥': 'sk-review-secret',
  'AI评分模型': 'review-model',
  '等待确认分钟': 30,
  '官方QQ图片按钮延迟秒': 0,
};
let registered = null;
let fetchCount = 0;
let lastFetchOptions = null;
const responses = [];

const fishingExt = {
  storageGet: key => fishingStorage.get(String(key)) || '',
  storageSet: (key, value) => fishingStorage.set(String(key), String(value)),
};

const seal = {
  ext: {
    find: name => name === 'fishingSystemV2' ? fishingExt : null,
    new: (name, author, version) => ({ name, author, version, cmdMap: {} }),
    register: ext => { registered = ext; },
    registerStringConfig: (_ext, name, value) => {
      if (!Object.prototype.hasOwnProperty.call(configs, name)) configs[name] = value;
    },
    registerIntConfig: (_ext, name, value) => {
      if (!Object.prototype.hasOwnProperty.call(configs, name)) configs[name] = value;
    },
    getStringConfig: (_ext, name) => String(configs[name] || ''),
    getIntConfig: (_ext, name) => Number(configs[name] || 0),
    newCmdItemInfo: () => ({}),
    newCmdExecuteResult: value => ({ matched: value }),
  },
  identity: {
    canonicalUserId: () => 'OpenQQ:user',
  },
  replyToSender: (_ctx, _msg, text) => replies.push(String(text)),
  vars: {
    intSet: () => {},
    strSet: () => {},
    intGet: () => [0, false],
    strGet: () => ['', false],
  },
};

global.seal = seal;
global.fetch = async (_url, options) => {
  fetchCount += 1;
  lastFetchOptions = options;
  const value = responses.shift();
  if (!value) throw new Error('unexpected fetch');
  return { ok: true, status: 200, json: async () => value };
};

vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'), { filename: process.argv[2] });
if (!registered || !registered.cmdMap['角色卡评分']) throw new Error('角色卡评分指令未注册');

registered.storageGet = key => pluginStorage.get(String(key)) || '';
registered.storageSet = (key, value) => pluginStorage.set(String(key), String(value));

const ctx = {
  player: { userId: 'OpenQQ:user', id: 'user' },
  group: { groupId: 'OpenQQ-Group:g' },
  endPoint: { platform: 'OpenQQ' },
};
const msg = {
  platform: 'OpenQQ',
  groupId: 'OpenQQ-Group:g',
  sender: { userId: 'OpenQQ:user', id: 'user' },
};
const scope = 'OpenQQ-Group:g|OpenQQ:user';
pluginStorage.set('last_cards', JSON.stringify({
  [scope]: { token: 'card-token', character: '林雾', createdAt: Date.now() },
}));

function wallet(coins) {
  return {
    coins,
    total: 20,
    success: 12,
    collection: ['鲤鱼王'],
    inventory: { '普通鱼饵': 10 },
    history: [],
  };
}

const fullKey = 'OpenQQ:user_pokemon_fish_v1';
const aliasKey = 'user_pokemon_fish_v1';
fishingStorage.set(fullKey, JSON.stringify(wallet(50)));
fishingStorage.set(aliasKey, JSON.stringify(wallet(50)));

function reviewResponse(aiUsed, totalTokens) {
  return {
    ok: true,
    review_image_url: 'https://example.com/review.png',
    review: {
      name: '林雾', clarity_score: 88, completeness_score: 84,
      interest_score: 91, total_score: 88, verdict: '人物关系鲜明',
      ella_comment: '这份牵挂很真', review_source: aiUsed ? 'ai' : 'local',
      total_tokens: totalTokens,
    },
    billing: {
      ai_used: aiUsed,
      total_tokens: totalTokens,
      pokecoin_charge: aiUsed ? (totalTokens > 50000 ? 200 : 100) : 0,
      usage_estimated: false,
    },
  };
}

async function main() {
  responses.push(reviewResponse(true, 50001));
  await registered.cmdMap['角色卡评分'].solve(ctx, msg, {});
  if (!replies.some(text => text === '这次是预言系的魔法哦~艾拉正在仪式施法，请耐心等待，应该比十分钟要快一些吧……')) {
    throw new Error('角色卡评分没有先发送预言系魔法提示');
  }
  const requestBody = JSON.parse(lastFetchOptions.body);
  if (requestBody.review_ai.api_url !== 'https://ai.example.com/v1' ||
      requestBody.review_ai.api_key !== 'sk-review-secret' ||
      requestBody.review_ai.model !== 'review-model') {
    throw new Error('海豹后台AI评分配置没有传给本机后端');
  }
  const fullAfter = JSON.parse(fishingStorage.get(fullKey));
  const aliasAfter = JSON.parse(fishingStorage.get(aliasKey));
  if (fullAfter.coins !== -150 || aliasAfter.coins !== -150) {
    throw new Error('AI评分没有向全部关联钓鱼账户扣除200宝可元');
  }
  if (!fullAfter.isDebtor || fullAfter.debt !== 150) throw new Error('扣成负数后没有建立负债状态');
  if (!replies.some(text => text.includes('消耗 50001 Token') && text.includes('余额 -150'))) {
    throw new Error('成功评分没有返回Token和余额');
  }

  await registered.cmdMap['角色卡评分'].solve(ctx, msg, {});
  if (fetchCount !== 1) throw new Error('负债后仍然调用了AI评分接口');
  if (!replies.some(text => text.includes('还清负债前无法使用'))) throw new Error('负债门禁没有明确回执');

  fishingStorage.set(fullKey, JSON.stringify(wallet(500)));
  fishingStorage.set(aliasKey, JSON.stringify(wallet(500)));
  responses.push(reviewResponse(false, 0));
  await registered.cmdMap['角色卡评分'].solve(ctx, msg, {});
  if (JSON.parse(fishingStorage.get(fullKey)).coins !== 500) throw new Error('默认评分错误扣除了宝可元');
  if (!replies.some(text => text.includes('默认评分且未扣宝可元'))) throw new Error('默认回退没有明确提示');

  const fetchBeforeMissingConfig = fetchCount;
  configs['AI评分API密钥'] = '';
  await registered.cmdMap['角色卡评分'].solve(ctx, msg, {});
  if (fetchCount !== fetchBeforeMissingConfig) throw new Error('AI配置不完整时仍然调用了后端');
  if (!replies.some(text => text.includes('海豹 WebUI') && text.includes('AI评分API密钥'))) {
    throw new Error('AI配置缺失时没有指向海豹后台');
  }

  console.log('AUTOCARD BILLING TEST PASSED');
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
