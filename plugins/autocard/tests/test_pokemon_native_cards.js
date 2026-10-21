const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const extensions = new Map(), replies = [], cards = new Map(), configs = new Map();
const clone = x => JSON.parse(JSON.stringify(x));
const ctx = {player: {userId:'OpenQQ:owner', name:'甲'}, group:{groupId:'OpenQQ-Group:test'}, rule:'旅伴规则', card:'a'};
const msg = {groupId:ctx.group.groupId, sender:{userId:ctx.player.userId}, platform:'OpenQQ'};
function blank(id, name=id) {cards.set(id,{id,name,bound:true,sheetType:'旅伴规则',ints:{},strings:{}});}
blank('a');blank('b');blank('migration');
const seal = {
  ext:{
    find:name=>extensions.get(name)||null,
    new:(name,author,version)=>{const storage=new Map();return {name,version,cmdMap:{},storageGet:key=>storage.get(key)||'',storageSet:(key,value)=>storage.set(key,value)};},
    register:ext=>extensions.set(ext.name,ext),
    registerStringConfig:(_,key,value)=>configs.set(key,value), registerIntConfig:(_,key,value)=>configs.set(key,value),
    getStringConfig:(_,key)=>configs.get(key),getIntConfig:(_,key)=>configs.get(key),
    newCmdItemInfo:()=>({}),newCmdExecuteResult:ok=>({solved:ok}),
  },
  format:(c,s)=>s.includes('游戏模式')?c.rule:c.player.name,
  vars:{strGet:(c,key)=>key==='$t游戏模式'?[c.rule,true]:['',false]},
  character:{getCurrent:c=>clone(cards.get(c.card)),patchCurrent:(c,id,type,json)=>{
    const target=cards.get(c.card);assert.equal(id,target.id);assert.equal(type,target.sheetType);assert(target.bound);
    for(const [k,v] of Object.entries(JSON.parse(json))) (typeof v==='number'?target.ints:target.strings)[k]=v;
    return clone(target);
  }},
  gameSystem:{newTemplateByYaml:json=>{const t=JSON.parse(json);assert.equal(t.commands.set.diceSides,'20');assert.equal(t.name,'旅伴规则');}},
  getCtxProxyFirst:c=>c,replyToSender:(_,__,text)=>replies.push(text),setPlayerGroupCard:()=>{},
};
const sandbox={seal,console,Date,setTimeout};
const pokemon=fs.readFileSync(process.env.AUTOCARD_POKEMON_PLUGIN_PATH || path.join(root,'../pokemon-assistant/payload/pokemon.js'),'utf8');
const autocard=fs.readFileSync(path.join(root,'sealdice/一键录卡.js'),'utf8');
const run=source=>vm.runInNewContext(source,sandbox);
run(pokemon);
const plugin=extensions.get('门版宝可梦TRPG综合助手v1.38.51');
run(autocard.replace(/\}\)\(\);\s*$/, 'globalThis.applyPokemon=applyPokemonRecord;})();'));
// A Go-backed extension does not expose arbitrary JS API properties to peers.
delete plugin.autocardApiV1;
const record=(name,value,count=2)=>({name,values:{hpmax:30,hp:12,探查:value,武士道:-2},pokemon:Array.from({length:count},(_,i)=>({name:name+i,species:'电电虫',types:['虫','电'],stat_modifiers:{特攻:4},accuracy:3,evasion:9,moves:[{name:'信号光束',element:'虫',category:'特殊',damage:'2D4+1D6'}]}))});
const args=text=>({rawArgs:text,cleanArgs:text,getArgN:i=>text.split(/\s+/)[i-1]||''});
const command=(name,text='')=>plugin.cmdMap[name].solve(ctx,msg,args(text));
const last=()=>replies.at(-1).replace(/\s/g,'');
sandbox.applyPokemon(ctx,msg,record('甲虫',3,25),'a');
assert.equal(cards.get('a').ints.探查,3);
assert.equal(JSON.parse(cards.get('a').strings.$pkmRecordV1).pokemon.length,25);
assert.equal(plugin.storageGet('pokemon_player_data'),'','native imports must not duplicate a global user roster');
ctx.card='b';command('宝可梦队伍');assert(!replies.at(-1).includes('甲虫'));
sandbox.applyPokemon(ctx,msg,record('乙虫',8),'b');
command('pm','探查');assert(last().includes('+8'));
ctx.card='a';command('pm','探查');assert(last().includes('+3'));
command('宝可梦伤害','甲虫0 草 信号光束');assert(replies.at(-1).toLowerCase().includes('2d4+1d6'));
command('宝可梦队伍');assert(!replies.at(-1).includes('乙虫'));
cards.get('a').ints.探查=11;command('pm','探查');assert(last().includes('+11'));
command('pst','hp-2 探查-1');assert.equal(cards.get('a').ints.hp,10);assert.equal(cards.get('a').ints.探查,-1);
assert.throws(()=>sandbox.applyPokemon(ctx,msg,record('坏',99),'b'),/切换/);
assert.equal(cards.get('a').ints.探查,-1);
ctx.rule='coc7';const ordinary={message:'.ra 侦查',segment:[{content:'.ra 侦查'}]};plugin.onMessageReceived(ctx,ordinary);assert.equal(ordinary.message,'.ra 侦查');
ctx.rule='旅伴规则';const pkm={message:'.ra探查',segment:[{content:'.ra'},{content:'探查'}]};plugin.onMessageReceived(ctx,pkm);assert.equal(pkm.message,'.pm探查');assert.equal(pkm.segment[0].content,'.pm探查');
cards.get('a').sheetType='dnd5e';command('pst','hp99');assert(replies.at(-1).includes('当前绑定'));assert.equal(cards.get('a').ints.hp,10);cards.get('a').sheetType='旅伴规则';
// Reload uses per-card integers, not stale in-memory trainer JSON.
run(pokemon);command('pm','探查');assert(last().includes('-1'));
// Explicit migration copies once into an empty bound card, keeping the source.
plugin.storageSet('pokemon_player_data',JSON.stringify({'OpenQQ:owner':{trainer:{探查:4,hp:7},pokemon:[{name:'旧伙伴',moves:[]}],meta:{}}}));
run(pokemon);ctx.card='migration';command('宝可梦迁移');assert.equal(cards.get('migration').ints.hp,7);assert(replies.at(-1).includes('已将'));
command('宝可梦迁移');assert(replies.at(-1).includes('已有数据'));
blank('extra');ctx.card='extra';command('宝可梦迁移');assert(replies.at(-1).includes('已经迁移过'));assert.deepEqual(cards.get('extra').ints,{});
assert(JSON.parse(plugin.storageGet('pokemon_player_data'))['OpenQQ:owner'].pokemon.length===1);
console.log('Native card JS: isolated 25-member import, damage, skills, edits, migration, reload and stale/wrong-card guards passed.');
