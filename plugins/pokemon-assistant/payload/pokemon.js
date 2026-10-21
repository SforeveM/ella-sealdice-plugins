// ==UserScript==
// @name         门版宝可梦TRPG综合助手 v1.39.1
// @author       中二的灰石门, 星言, SNOM
// @version      1.39.1
// @description  .sn pkm/.sn 旅伴自动名片；原生旅伴角色卡、D20检定及组合伤害骰
// @license      MIT
// @timestamp    2026-03-24
// ==/UserScript==

// 不再用 `if (!find(...))` 包住整份脚本。海豹热更新后即使旧扩展对象
// 仍驻留内存，本脚本也会复用它、覆盖命令并重新挂载 autocardApiV1。
// 优先复用 v1.38.51 的存储命名空间，旧 .pst 数据无需迁移即可保留。
{
    const storedExt = seal.ext.find('门版宝可梦TRPG综合助手v1.38.51');
    const bridgeExt = seal.ext.find('门版宝可梦TRPG综合助手v1.38.52');
    let ext = storedExt || bridgeExt;
    const migrationExt = ext === storedExt ? bridgeExt : storedExt;
    if (!ext) {
        ext = seal.ext.new('门版宝可梦TRPG综合助手v1.38.51', '中二的灰石门, 星言, SNOM', '1.39.1');
        seal.ext.register(ext);
    }
    try { ext.version = '1.39.1'; } catch (_) {}
    const PKM_RULE = '旅伴规则';
    const PKM_DATA = '$pkmRecordV1';
    const isPkm = ctx => String(seal.format(ctx, '{$t游戏模式}') || '') === PKM_RULE;
    const requireCard = ctx => {
        if (!seal.character || typeof seal.character.patchCurrent !== 'function') {
            throw new Error('需要配套的私人核心 v1.4.7（旅伴角色卡版），请联系骰主更新核心。');
        }
        if (!isPkm(ctx)) throw new Error('请先发送 .set pkm 切换到旅伴规则。');
        const card = seal.character.getCurrent(ctx);
        if (!card.bound) throw new Error('请先发送 .pc new 角色名 创建并绑定旅伴卡，或 .pc tag 角色名 切换已有卡。');
        if (card.sheetType !== PKM_RULE) throw new Error('当前绑定的是' + card.sheetType + '角色卡。请用 .pc new 角色名 新建旅伴卡，或 .pc tag 角色名 切换；没有改动当前卡。');
        return card;
    };

    // ==========================================
    // 插件后台可视化设置注册
    // ==========================================
    seal.ext.registerStringConfig(
        ext,
        "训练家名片模板",
        "{name} HP{hp}/{hpmax} TP{旅行点} IP{物资点}",
        "训练家名片模板。可用占位符：{name} {hp} {hpmax} {旅行点} {物资点}"
    );


    // ==========================================
    // 帮助函数
    // ==========================================
    const getHelpText = (topicRaw) => {
        const topic = (topicRaw || "").trim();
        if (!topic) return HELP_INDEX;
        if (["录卡", "录入", "pst"].includes(topic)) return HELP_RECORD;
        if (["检定", "pm"].includes(topic)) return HELP_CHECK;
        if (["名片", "th"].includes(topic)) return HELP_CARD;
        if (["生成", "xlj", "xljx"].includes(topic)) return HELP_GEN;
        if (["代操", "@", "委托", "代理"].includes(topic)) return HELP_DELEGATE;
        if (["伤害", "伤害骰", "宝可梦伤害", "pkdmg"].includes(topic)) return HELP_DAMAGE;
        if (["队伍", "宝可梦队伍"].includes(topic)) return HELP_TEAM;
        return `未找到 "${topic}" 对应的帮助。\n\n${HELP_INDEX}`;
    };

    // ==========================================
    // 工具函数
    // ==========================================
    const rollDie = sides => Math.floor(Math.random() * sides) + 1;

    const rollSingleStat = () => {
        let rolls = Array.from({length:4},()=>rollDie(6)).sort((a,b)=>b-a);
        let sum = rolls[0]+rolls[1]+rolls[2];

        if (sum === 18) {
            const extra = rollDie(6);
            if (extra <= 2) sum = 16;
            else if (extra === 3) sum = 17;
            else if (extra === 4) sum = 18;
            else if (extra === 5) sum = 19;
            else if (extra === 6) sum = 20;
        } else if (sum === 17) {
            const extra = rollDie(6);
            if (extra <= 2) sum = 15;
            else if (extra <= 4) sum = 16;
            else if (extra === 5) sum = 17;
            else if (extra === 6) sum = 19;
        }

        return SPECIAL_STATS[sum] || sum.toString();
    };

    const statToNumber = stat => {
        for (const key in SPECIAL_STATS) {
            if (SPECIAL_STATS[key] === stat) return parseInt(key, 10);
        }
        return parseInt(stat,10)||0;
    };


    const generateStatGroups = (groupCount=1, fixed=false) => {
        const results = [];
        for (let i=0;i<groupCount;i++){
            let stats = [];
            let total = 0;
            for (let attr of ATTRIBUTES){
                const stat = rollSingleStat();
                stats.push(fixed ? `${attr}:${stat}` : stat);
                total += statToNumber(stat);
            }
            results.push(fixed ? `${stats.join(", ")}, 共计:${total}` : `${stats.join(", ")} = ${total}`);
        }
        return results.join("\n\n");
    };

    const getArgsText = (cmdArgs, startIndex=1) => {
        let text = '';
        let i = startIndex;
        let arg = cmdArgs && cmdArgs.getArgN ? cmdArgs.getArgN(i) : '';
        while (arg) {
            text += arg + ' ';
            i++;
            arg = cmdArgs.getArgN(i);
        }
        return text.replace(/\[CQ:[^\]]+\]/g, '').trim();
    };

    const getRawMessageText = (msg) => {
        return String(
            (msg && (msg.message || msg.rawMessage || msg.raw || msg.text || msg.content)) || ''
        ).trim();
    };

    const getCommandInputText = (msg, cmdArgs, cmdName, startIndex=1) => {
        const byArgs = getArgsText(cmdArgs, startIndex);
        if (byArgs) return byArgs;

        const raw = getRawMessageText(msg);
        if (!raw) return '';

        const escapedCmd = String(cmdName).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const match = raw.match(new RegExp(`^[\\.。／/]${escapedCmd}(.*)$`, 'i'));
        return match ? match[1].trim() : '';
    };

    const normalizePmInputText = (text) => {
        return String(text || '')
            .trim()
            .replace(/　/g, ' ')
            .replace(/\s+/g, '')
            .replace(/＋/g, '+')
            .replace(/－/g, '-')
            .replace(/＃/g, '#')
            .toLowerCase();
    };

    const parsePmRepeatPrefix = (expr) => {
        let repeat = 1;
        let text = expr;

        const match = text.match(/^(\d+)#(.*)$/);
        if (match) {
            repeat = parseInt(match[1], 10);
            text = match[2] || '';
        }

        if (!Number.isFinite(repeat) || repeat <= 0) {
            return { ok: false, reason: '重复次数必须大于 0。' };
        }

        if (repeat > MAX_GROUPS) {
            return { ok: false, reason: `重复次数不能超过 ${MAX_GROUPS} 次。` };
        }

        return { ok: true, repeat, expr: text };
    };

    const stripPmModeTokens = (expr) => {
        let text = expr;
        const found = new Set();

        const tokens = [
            { mode: 'adv', prefix: /^(?:优势|advantage|adv)/, suffix: /(?:优势|advantage|adv)$/ },
            { mode: 'dis', prefix: /^(?:劣势|disadvantage|dis)/, suffix: /(?:劣势|disadvantage|dis)$/ }
        ];

        let changed = true;
        while (changed) {
            changed = false;
            for (const token of tokens) {
                if (token.prefix.test(text)) {
                    text = text.replace(token.prefix, '');
                    found.add(token.mode);
                    changed = true;
                }
                if (token.suffix.test(text)) {
                    text = text.replace(token.suffix, '');
                    found.add(token.mode);
                    changed = true;
                }
            }
        }

        if (found.size > 1) {
            return { ok: false, reason: '不能同时使用优势和劣势。' };
        }

        return {
            ok: true,
            mode: found.size === 1 ? Array.from(found)[0] : 'normal',
            expr: text
        };
    };

    const isDiceLikeBody = (expr) => {
        if (!expr) return true;
        return /^[\dd+\-]+$/.test(expr) && (expr.includes('d') || /^[+\-]\d+$/.test(expr));
    };

    const parseDiceBody = (expr, mode) => {
        let text = expr;

        if (!text) {
            text = '1d20';
        } else if (/^[+\-]\d+$/.test(text)) {
            text = `1d20${text}`;
        }

        const match = text.match(/^(\d*)d(\d*)([+\-]\d+)?$/);
        if (!match) return null;

        const count = match[1] ? parseInt(match[1], 10) : 1;
        const sides = match[2] ? parseInt(match[2], 10) : 20;
        const modifier = parseInt(match[3] || '0', 10);

        if (!Number.isFinite(count) || !Number.isFinite(sides) || !Number.isFinite(modifier)) {
            return { ok: false, reason: '骰式中含有无效数字。' };
        }
        if (count <= 0 || sides <= 0) {
            return { ok: false, reason: '骰子数量和面数必须大于 0。' };
        }
        if (count > 100 || sides > 1000 || Math.abs(modifier) > 100000) {
            return { ok: false, reason: '骰式超出允许范围。' };
        }

        if (mode !== 'normal' && !(count === 1 && sides === 20)) {
            return { ok: false, reason: '优势/劣势目前只支持 d20 系检定，例如：.pm 优势探查 / .pm 劣势+2 / .pm 3#优势探查-1' };
        }

        return {
            ok: true,
            count,
            sides,
            modifier,
            normalized: `${count}d${sides}${modifier === 0 ? '' : (modifier > 0 ? `+${modifier}` : `${modifier}`)}`
        };
    };

    const parseSkillBody = (expr) => {
        if (!expr) return null;
        const match = expr.match(/^(.+?)([+\-]\d+)?$/);
        if (!match) return null;

        const skillName = (match[1] || '').trim();
        if (!skillName) return null;

        const tempModifier = parseInt(match[2] || '0', 10);
        if (!Number.isFinite(tempModifier)) return null;

        return {
            ok: true,
            skillName,
            tempModifier
        };
    };

    const parsePmRequest = (text) => {
        let expr = normalizePmInputText(text);
        if (!expr) {
            return { ok: false, reason: '请输入技能名或骰式。' };
        }

        const repeatParsed = parsePmRepeatPrefix(expr);
        if (!repeatParsed.ok) return repeatParsed;
        expr = repeatParsed.expr;

        const modeParsed = stripPmModeTokens(expr);
        if (!modeParsed.ok) return modeParsed;
        expr = modeParsed.expr;

        const diceParsed = parseDiceBody(expr, modeParsed.mode);
        if (diceParsed && diceParsed.ok) {
            return {
                ok: true,
                type: 'dice',
                repeat: repeatParsed.repeat,
                mode: modeParsed.mode,
                count: diceParsed.count,
                sides: diceParsed.sides,
                modifier: diceParsed.modifier,
                normalized: diceParsed.normalized
            };
        }
        if (diceParsed && diceParsed.ok === false) {
            return diceParsed;
        }

        if (isDiceLikeBody(expr)) {
            return { ok: false, reason: '自定义掷骰格式错误。' };
        }

        const skillParsed = parseSkillBody(expr);
        if (skillParsed && skillParsed.ok) {
            return {
                ok: true,
                type: 'skill',
                repeat: repeatParsed.repeat,
                mode: modeParsed.mode,
                skillName: skillParsed.skillName,
                tempModifier: skillParsed.tempModifier
            };
        }

        return { ok: false, reason: '未能识别这条 .pm 指令，请检查格式。' };
    };

    const formatSignedTerm = (value, showZero=false) => {
        if (value > 0) return ` + ${value}`;
        if (value < 0) return ` - ${Math.abs(value)}`;
        return showZero ? ' + 0' : '';
    };

    const buildDiceCheckLine = (parsed) => {
        if (parsed.mode === 'adv' || parsed.mode === 'dis') {
            const r1 = rollDie(20);
            const r2 = rollDie(20);
            const kept = parsed.mode === 'adv' ? Math.max(r1, r2) : Math.min(r1, r2);
            const modeText = parsed.mode === 'adv' ? '优势' : '劣势';
            const keepText = parsed.mode === 'adv' ? '高' : '低';
            const total = kept + parsed.modifier;

            let text = `${modeText}检定: 2d20(${r1},${r2}) 取${keepText} ${kept}${formatSignedTerm(parsed.modifier)} = ${total}`;
            if (kept === 20) text += ' [大成功!]';
            if (kept === 1) text += ' [大失败!]';
            return text;
        }

        const rolls = Array.from({ length: parsed.count }, () => rollDie(parsed.sides));
        const rollSum = rolls.reduce((a, b) => a + b, 0);
        const total = rollSum + parsed.modifier;

        let text = `${parsed.count}d${parsed.sides}(${rolls.join('+')})${formatSignedTerm(parsed.modifier)} = ${total}`;

        if (parsed.count === 1 && parsed.sides === 20) {
            if (rolls[0] === 20) text += ' [大成功!]';
            if (rolls[0] === 1) text += ' [大失败!]';
        }

        return text;
    };

    const buildSkillCheckLine = (skillName, skillValue, tempModifier, mode) => {
        if (mode === 'adv' || mode === 'dis') {
            const r1 = rollDie(20);
            const r2 = rollDie(20);
            const kept = mode === 'adv' ? Math.max(r1, r2) : Math.min(r1, r2);
            const modeText = mode === 'adv' ? '优势' : '劣势';
            const keepText = mode === 'adv' ? '高' : '低';
            const total = kept + skillValue + tempModifier;

            let text = `${skillName}${modeText}检定: 2d20(${r1},${r2}) 取${keepText} ${kept}${formatSignedTerm(skillValue, true)}${formatSignedTerm(tempModifier)} = ${total}`;
            if (kept === 20) text += ' [大成功!]';
            if (kept === 1) text += ' [大失败!]';
            return text;
        }

        const dice = rollDie(20);
        const total = dice + skillValue + tempModifier;

        let text = `${skillName}检定: 1d20(${dice})${formatSignedTerm(skillValue, true)}${formatSignedTerm(tempModifier)} = ${total}`;
        if (dice === 20) text += ' [大成功!]';
        if (dice === 1) text += ' [大失败!]';
        return text;
    };

    const buildRepeatedResultText = (playerName, header, lines) => {
        if (lines.length === 1) {
            return `${playerName} 的${header}${lines[0]}`;
        }
        return `${playerName} 的${header}\n` + lines.map((line, idx) => `${idx + 1}. ${line}`).join('\n');
    };

    const extractStickyPmText = (msg) => {
        const raw = getRawMessageText(msg);
        if (!raw) return '';

        const match = raw.match(/^[\.。／/]pm(.*)$/i);
        if (!match) return '';

        return String(match[1] || '').trim();
    };

    const normalizeAttrName = (name) => {
        const raw = (name || "").trim();
        return ALIAS_TO_CANONICAL[raw] || ALIAS_TO_CANONICAL[raw.toLowerCase()] || raw;
    };

    const isOfficialQQContext = (ctx, msg) => {
        const values = [msg && msg.groupId, ctx && ctx.group && ctx.group.groupId];
        return values.some(value => /^OpenQQ-Group:/i.test(cleanText(value)));
    };
    const buildOfficialQQInputButtonsMarker = commands => {
        const rows = (Array.isArray(commands) ? commands : []).filter(item =>
            item && item.label && /^\.[^;|\]\r\n]{1,127}$/.test(cleanText(item.data))
        );
        if (!rows.length) return '';
        return '[SealDice-OfficialQQ-InputButtons:' + rows.slice(0, 5)
            .map(item => `${cleanText(item.label)}|${cleanText(item.data)}`).join(';') + ']';
    };

    // 半自动卡导出的紧凑文本可能把单位写在下一个字段前面，
    // 例如“旅行点7TP物资点11IP力气-1”。普通正则会得到
    // “TP物资点”和“IP力气”，这里按最长已知后缀还原真实字段。
    const normalizePstAttrName = (name) => {
        const raw = (name || "").trim();
        const lower = raw.toLowerCase();
        let bestAlias = '';
        for (const alias of Object.keys(ALIAS_TO_CANONICAL)) {
            if (lower.endsWith(alias.toLowerCase()) && alias.length > bestAlias.length) {
                bestAlias = alias;
            }
        }
        return bestAlias ? normalizeAttrName(bestAlias) : normalizeAttrName(raw);
    };

    // 门版宝可梦空白卡 v1.3 会把导入内容连续拼接成：
    // HPmax21HP旅行点10物资点10……。当“当前HP”留空时，HP 标签后
    // 没有数字，旧解析器会把它和“旅行点”粘成同一个字段。这里保留
    // 原有宽松解析，并只在识别到这一明确结构时把当前 HP 补为 HP 上限。
    const parsePstEntries = text => {
        const source = String(text || '')
            .replace(/　/g, ' ')
            .replace(/＋/g, '+')
            .replace(/－/g, '-')
            .replace(/^[\.。／\/]?pst(?:\s+|(?=[^\x00-\x7F]))/i, '')
            .trim();
        const blankCurrentHpFromV13 = /hpmax\s*[+\-]?\d+\s*hp\s*(?=(?:旅行点|tp)\s*[+\-]?\d+)/i.test(source);
        const regex = /([^\d\s\+\-]+)\s*([\+\-]?\d+)/g;
        const entries = [];
        let match;

        while ((match = regex.exec(source)) !== null) {
            const rawName = match[1].trim();
            const attrName = normalizePstAttrName(rawName);
            if (!attrName || CARD_V13_EMPTY_SKILL_NAMES.has(attrName)) continue;
            const rawValStr = match[2].trim();
            const value = parseInt(rawValStr, 10);
            if (!Number.isFinite(value)) continue;
            entries.push({ rawName, attrName, rawValStr, value });
        }

        if (blankCurrentHpFromV13 && !entries.some(item => item.attrName === 'hp')) {
            const hpmax = entries.find(item => item.attrName === 'hpmax');
            if (hpmax) {
                entries.push({
                    rawName: 'HP（空白卡v1.3默认）',
                    attrName: 'hp',
                    rawValStr: String(Math.max(0, hpmax.value)),
                    value: Math.max(0, hpmax.value),
                    inferred: true
                });
            }
        }

        return entries;
    };

    const getStoredValue = (dataObj, canonicalName) => {
        if (!dataObj) return 0;
        if (dataObj[canonicalName] !== undefined) return dataObj[canonicalName];

        const aliases = ATTR_ALIASES[canonicalName] || [];
        for (const alias of aliases) {
            if (dataObj[alias] !== undefined) return dataObj[alias];
            if (dataObj[alias.toLowerCase()] !== undefined) return dataObj[alias.toLowerCase()];
        }
        return 0;
    };

    const hasStoredValue = (dataObj, canonicalName) => {
        if (!dataObj) return false;
        if (dataObj[canonicalName] !== undefined) return true;

        const aliases = ATTR_ALIASES[canonicalName] || [];
        for (const alias of aliases) {
            if (dataObj[alias] !== undefined) return true;
            if (dataObj[alias.toLowerCase()] !== undefined) return true;
        }
        return false;
    };

    // ==========================================
    // 玩家训练家数据接口
    // ==========================================
    const ensureLegacyRecord = (playerId) => {
        if (!playerData[playerId]) {
                playerData[playerId] = {
                    trainer: {},
                    pokemon: [],
                    meta: {}
                };
        } else {
            // 兼容旧版直接把训练家属性写在 playerData[playerId] 里的存档
            if (!playerData[playerId].trainer) {
                playerData[playerId] = {
                    trainer: playerData[playerId],
                    pokemon: [],
                    meta: {}
                };
            }
            if (!Array.isArray(playerData[playerId].pokemon)) playerData[playerId].pokemon = [];
            if (!playerData[playerId].meta) playerData[playerId].meta = {};
        }
        return playerData[playerId];
    };

    const getRecord = ctx => {
        if (!isPkm(ctx)) return ensureLegacyRecord(String(ctx.player.userId));
        const card = requireCard(ctx);
        const raw = (card.strings || {})[PKM_DATA];
        // A damaged saved roster must not silently become an empty replacement.
        const stored = raw ? JSON.parse(raw) : { pokemon: [], meta: {} };
        if (!stored || !Array.isArray(stored.pokemon)) throw new Error('当前旅伴卡的队伍数据损坏，请联系骰主恢复备份。');
        const trainer = {};
        Object.keys(card.ints || {}).forEach(key => {
            if (!key.startsWith('$')) trainer[normalizeAttrName(key)] = Number(card.ints[key]);
        });
        return { trainer, pokemon: stored.pokemon, meta: stored.meta || {}, cardId: card.id };
    };
    const getTrainerData = ctx => getRecord(ctx).trainer;

    const cleanText = value => String(value === undefined || value === null ? '' : value).trim();

    const cleanNumber = (value, fallback=0) => {
        const number = Number(value);
        return Number.isFinite(number) ? Math.trunc(number) : fallback;
    };

    const sanitizeMove = raw => {
        const move = raw && typeof raw === 'object' ? raw : {};
        return {
            name: cleanText(move.name),
            category: cleanText(move.category),
            element: cleanText(move.element),
            accuracy: cleanText(move.accuracy),
            damage: cleanText(move.damage),
            range: cleanText(move.range),
            ep_cost: Math.max(0, cleanNumber(move.ep_cost, 0)),
            priority: cleanNumber(move.priority, 0),
            effect: cleanText(move.effect)
        };
    };

    const sanitizePokemon = raw => {
        const pokemon = raw && typeof raw === 'object' ? raw : {};
        const cleanMap = source => {
            const result = {};
            const input = source && typeof source === 'object' ? source : {};
            Object.keys(input).forEach(key => {
                const value = Number(input[key]);
                if (Number.isFinite(value)) result[cleanText(key)] = Math.trunc(value);
            });
            return result;
        };
        return {
            name: cleanText(pokemon.name),
            species: cleanText(pokemon.species),
            gender: cleanText(pokemon.gender),
            types: (Array.isArray(pokemon.types) ? pokemon.types : [])
                .map(cleanText).filter(Boolean).slice(0, 2),
            ability: cleanText(pokemon.ability),
            held_item: cleanText(pokemon.held_item),
            status: cleanText(pokemon.status),
            bond: cleanNumber(pokemon.bond, 0),
            hp: Math.max(0, cleanNumber(pokemon.hp, 0)),
            hpmax: Math.max(0, cleanNumber(pokemon.hpmax, 0)),
            ep: Math.max(0, cleanNumber(pokemon.ep, 0)),
            accuracy: cleanNumber(pokemon.accuracy, 0),
            evasion: cleanNumber(pokemon.evasion, 0),
            stats: cleanMap(pokemon.stats),
            stat_modifiers: cleanMap(pokemon.stat_modifiers),
            moves: (Array.isArray(pokemon.moves) ? pokemon.moves : [])
                .map(sanitizeMove).filter(move => move.name).slice(0, 24)
        };
    };

    const normalizeLookupText = value => cleanText(value)
        .toLowerCase().replace(/[\s·・‧.'’“”\-_]/g, '');

    const normalizeType = value => {
        const key = normalizeLookupText(value);
        return TYPE_ALIASES[key] || '';
    };

    const parseTypeSpec = raw => cleanText(raw)
        .split(/[\/／、,+，&＆]/)
        .map(normalizeType).filter(Boolean).slice(0, 2);

    const matchPokemon = (roster, query) => {
        const wanted = normalizeLookupText(query);
        if (!wanted) return { error: '请填写发动招式的宝可梦名字或种族名。' };
        const rows = (Array.isArray(roster) ? roster : []).filter(Boolean);
        const exactName = rows.filter(p => normalizeLookupText(p.name) === wanted);
        if (exactName.length === 1) return { pokemon: exactName[0] };
        const exactSpecies = rows.filter(p => normalizeLookupText(p.species) === wanted);
        if (exactSpecies.length === 1) return { pokemon: exactSpecies[0] };
        const partial = rows.filter(p => {
            const name = normalizeLookupText(p.name);
            const species = normalizeLookupText(p.species);
            return (name && (name.includes(wanted) || wanted.includes(name))) ||
                (species && (species.includes(wanted) || wanted.includes(species)));
        });
        if (partial.length === 1) return { pokemon: partial[0] };
        if (partial.length > 1 || exactName.length > 1 || exactSpecies.length > 1) {
            const choices = (partial.length ? partial : exactName.concat(exactSpecies))
                .map(p => p.name || p.species).filter(Boolean);
            return { error: `找到了多只符合的宝可梦：${choices.join('、')}。请改用角色卡里的昵称。` };
        }
        return { error: `队伍里没有找到“${query}”。发送 .宝可梦队伍 查看已录入的宝可梦。` };
    };

    const matchMove = (pokemon, query) => {
        const wanted = normalizeLookupText(query);
        const moves = Array.isArray(pokemon.moves) ? pokemon.moves : [];
        const exact = moves.filter(move => normalizeLookupText(move.name) === wanted);
        if (exact.length === 1) return { move: exact[0] };
        const partial = moves.filter(move => {
            const name = normalizeLookupText(move.name);
            return name && (name.includes(wanted) || wanted.includes(name));
        });
        if (partial.length === 1) return { move: partial[0] };
        if (partial.length > 1) {
            return { error: `招式名不够明确：${partial.map(move => move.name).join('、')}` };
        }
        const known = moves.map(move => move.name).filter(Boolean).join('、') || '暂无已录入招式';
        return { error: `${pokemon.name || pokemon.species}没有找到招式“${query}”。\n已录入招式：${known}` };
    };

    const formatModifier = value => {
        const number = cleanNumber(value, 0);
        if (number > 0) return `+${number}`;
        if (number < 0) return String(number);
        return '';
    };

    const combineDiceModifier = (rawDice, modifier) => {
        const dice = cleanText(rawDice).toUpperCase().replace(/\s+/g, '');
        if (!dice || dice === '—' || dice === '-' || /必定命中|必中/.test(dice)) return '';
        const match = dice.match(/^(\d*D\d+)([+\-]\d+)?$/i);
        if (!match) return '';
        const totalModifier = cleanNumber(match[2], 0) + cleanNumber(modifier, 0);
        return match[1] + formatModifier(totalModifier);
    };

    const typeMultiplier = (attackType, targetTypes) => {
        const row = TYPE_CHART[attackType] || {};
        let multiplier = 1;
        targetTypes.forEach(type => {
            const value = row[type];
            multiplier *= value === undefined ? 1 : value;
        });
        return multiplier;
    };

    const buildPowerTerm = (damage, stab, multiplier) => {
        const base = cleanText(damage).toUpperCase().replace(/\s+/g, '');
        const inner = stab ? `(${base}+${stab})` : `(${base})`;
        // 旅绊 v1.3 使用“分层”而非把最终伤害直接乘以属性倍率：
        // 第一层只翻倍/减半威力部分；第二层再处理攻方调整值。
        if (multiplier === 4 || multiplier === 2) return `${inner}*2`;
        if (multiplier === 0.5 || multiplier === 0.25) return `${inner}/2`;
        return stab ? `${base}+${stab}` : base;
    };

    const normalizePowerText = value => cleanText(value).toUpperCase()
        .replace(/\s+/g, '').replace(/[（]/g, '(').replace(/[）]/g, ')')
        .replace(/[，、]/g, ',').replace(/[－−]/g, '-').replace(/＋/g, '+');

    // The move tables contain sums such as 2D4+1D6, variable dice such as
    // XD4 / 2DX, and conditional alternatives such as 1D6(2D6).
    // Parse only the supported sum grammar; never evaluate sheet text as JS
    // or mistake a parenthetical alternative for multiplication.
    const powerSum = raw => {
        const source = normalizePowerText(raw);
        if (!source || source.length > 100) return null;
        const atom = '(?:\\d*D\\d+|[XN]D\\d+|\\d*D[XN]|[XN]|\\d+)';
        if (!(new RegExp('^[+-]?' + atom + '(?:[+-]' + atom + ')*$')).test(source)) return null;
        const notes = [];
        const expression = source.replace(/([XN])D(\d+)/g, (_, symbol, sides) => {
            notes.push(`${symbol}骰数按招式效果填写`);
            return `【${symbol}骰数】D${sides}`;
        }).replace(/(\d*)D([XN])/g, (_, count, symbol) => {
            notes.push(`${symbol}骰面按招式效果填写`);
            return `${count || '1'}D【${symbol}骰面】`;
        }).replace(/(^|[+\-])([XN])(?=$|[+\-])/g, (_, sign, symbol) => {
            notes.push(`${symbol}数值按招式效果填写`);
            return `${sign}【${symbol}数值】`;
        });
        return {expression, manual: notes.length > 0, notes: Array.from(new Set(notes))};
    };

    const describePower = raw => {
        const source = normalizePowerText(raw);
        const simple = powerSum(source);
        if (simple) return simple;
        const conditional = source.match(/^([^()]+)\(([^()]+)\)$/);
        if (conditional) {
            const base = powerSum(conditional[1]);
            const alternatives = conditional[2].split(',');
            if (base && alternatives.every(value => powerSum(value))) {
                const optionalAddition = alternatives.every(value => /^[+\-]/.test(value));
                return {
                    expression: optionalAddition ? base.expression + '+(【追加威力】)' : '【威力骰】',
                    manual: true,
                    notes: base.notes.concat(optionalAddition
                        ? [`追加威力无触发时填0；触发时按效果填写${alternatives.join('或')}`]
                        : [`按招式效果选择威力骰：${[conditional[1]].concat(alternatives).join('或')}`])
                };
            }
        }
        return {expression: '【威力骰】', manual: true, notes: ['按招式效果填写威力骰；原卡威力：' + cleanText(raw)]};
    };

    const maxDiceTotal = formula => {
        const source = cleanText(formula).toUpperCase().replace(/\s+/g, '').replace(/-/g, '+-');
        if (!source) return null;
        let total = 0;
        const parts = source.split('+').filter(Boolean);
        if (!parts.length) return null;
        for (const part of parts) {
            const dice = part.match(/^(-?\d*)D(\d+)$/i);
            if (dice) {
                let countText = dice[1];
                if (countText === '' || countText === '+') countText = '1';
                if (countText === '-') countText = '-1';
                const count = cleanNumber(countText, 0);
                // For a subtracted die, its minimum contributes to the
                // maximum of the whole expression: D6-D4 has a maximum of 5.
                total += count < 0 ? count : count * cleanNumber(dice[2], 0);
            } else if (/^-?\d+$/.test(part)) {
                total += cleanNumber(part, 0);
            } else {
                return null;
            }
        }
        return total;
    };

    const buildDamageGuide = (roster, rawText) => {
        let text = cleanText(rawText).replace(/　/g, ' ').replace(/\s+/g, ' ');
        if (!text || /^(?:help|帮助|指令)$/i.test(text)) return { help: true };

        let defenseValue = null;
        let defenseLabel = '';
        let targetEvasion = null;
        let critical = false;
        let suffixChanged = true;
        while (suffixChanged) {
            suffixChanged = false;
            const criticalMatch = text.match(/(?:\s|^)(要害|会心|暴击)\s*$/);
            if (criticalMatch) {
                critical = true;
                text = text.slice(0, criticalMatch.index).trim();
                suffixChanged = true;
                continue;
            }
            const evasionMatch = text.match(/(?:\s|^)(?:目标)?闪避\s*([+\-]?\d+)\s*$/);
            if (evasionMatch) {
                targetEvasion = cleanNumber(evasionMatch[1], 0);
                text = text.slice(0, evasionMatch.index).trim();
                suffixChanged = true;
                continue;
            }
            const defenseMatch = text.match(/(?:\s|^)(?:目标)?(防御|特防)\s*([+\-]?\d+)\s*$/);
            if (defenseMatch) {
                defenseLabel = defenseMatch[1];
                defenseValue = cleanNumber(defenseMatch[2], 0);
                text = text.slice(0, defenseMatch.index).trim();
                suffixChanged = true;
            }
        }

        const parts = text.split(' ').filter(Boolean);
        if (parts.length < 3) return { error: '格式不足。示例：.宝可梦伤害 皮卡丘 水/飞行 电光 防御1' };
        const pokemonQuery = parts.shift();
        let targetTypeText = parts.shift();
        if (parts.length >= 2 && normalizeType(targetTypeText) && normalizeType(parts[0])) {
            targetTypeText += '/' + parts.shift();
        }
        const moveQuery = parts.join(' ');
        const targetTypes = parseTypeSpec(targetTypeText);
        if (!targetTypes.length || targetTypes.length !== targetTypeText.split(/[\/／、,+，&＆]/).filter(Boolean).length) {
            return { error: `无法识别目标属性“${targetTypeText}”。双属性请写成 水/飞行。` };
        }

        const foundPokemon = matchPokemon(roster, pokemonQuery);
        if (foundPokemon.error) return foundPokemon;
        const pokemon = foundPokemon.pokemon;
        const foundMove = matchMove(pokemon, moveQuery);
        if (foundMove.error) return foundMove;
        const move = foundMove.move;
        const attackType = normalizeType(move.element);
        const category = cleanText(move.category);
        const multiplier = typeMultiplier(attackType, targetTypes);
        const hitDice = combineDiceModifier(move.accuracy, pokemon.accuracy);
        const title = `${pokemon.name || pokemon.species}（${pokemon.species || '种族未填'}）使用【${move.name}】`;
        const lines = [`【宝可梦招式骰指引】`, title,
            `招式：${move.element || '无属性'} / ${category || '类别未填'} / ${move.damage || '无威力骰'}`,
            `目标属性：${targetTypes.join('/')}｜克制倍率：×${multiplier}`,
            `EP消耗：${cleanNumber(move.ep_cost, 0)}｜卡面EP：${cleanNumber(pokemon.ep, 0)}（仅提示，不自动扣除）`];
        let hitCommand = '';
        let damageRollCommand = '';
        let editableDamage = false;

        if (hitDice) {
            hitCommand = `.r${hitDice}`;
            lines.push(`命中骰：${hitCommand}`);
            lines.push(targetEvasion === null
                ? '命中结果需大于目标闪避值；自然1必定失败，自然20为要害。'
                : `命中结果需大于目标闪避${targetEvasion}；也就是至少掷出${targetEvasion + 1}。`);
        } else if (/—|-|必定命中|必中/.test(cleanText(move.accuracy))) {
            lines.push('命中：此招式不使用普通命中骰；若规则要求检定要害，可输入 .rD20。');
        } else {
            lines.push(`命中：卡内命中骰“${move.accuracy || '未填写'}”无法自动换算，请查看招式说明。`);
        }

        if (multiplier === 0) {
            lines.push(`伤害：目标对${move.element}属性免疫，通常造成0点伤害。`);
        } else if (category === '变化' || !move.damage || /^(?:—|-|无)$/.test(cleanText(move.damage))) {
            lines.push('伤害：这是变化招式，不使用普通伤害骰。');
        } else if (/固定|MAX|最大|特殊计算/i.test(cleanText(move.damage))) {
            const fixedNumber = normalizePowerText(move.damage).match(/^固定(?:伤害)?[:：]?(\d+)$/);
            const isMaxHp = /^MAX$/i.test(cleanText(move.damage));
            editableDamage = !fixedNumber;
            damageRollCommand = '.r' + (fixedNumber ? fixedNumber[1] : isMaxHp ? '【目标最大HP】' : '【按效果填写伤害】');
            lines.push(`${editableDamage ? '伤害骰模板' : '伤害数值'}：${damageRollCommand}`);
            lines.push(`伤害：${move.damage}，按招式效果填写或结算，不额外套用普通威力的本系、攻防或克制加成。`);
        } else {
            const isPhysical = category === '物理';
            const isSpecial = category === '特殊';
            {
                const attackLabel = isPhysical ? '攻击' : isSpecial ? '特攻' : '攻击或特攻';
                const expectedDefense = isPhysical ? '防御' : isSpecial ? '特防' : '防御或特防';
                const modifiers = pokemon.stat_modifiers || {};
                const hasAttack = (isPhysical || isSpecial) && Object.prototype.hasOwnProperty.call(modifiers, attackLabel)
                    && modifiers[attackLabel] !== null && Number.isFinite(Number(modifiers[attackLabel]));
                const attackMod = hasAttack ? cleanNumber(modifiers[attackLabel], 0) : null;
                const ownTypes = (pokemon.types || []).map(normalizeType).filter(Boolean);
                const stab = ownTypes.includes(attackType) ? 3 : 0;
                const power = describePower(move.damage);
                const criticalPower = critical && !power.manual ? maxDiceTotal(power.expression) : null;
                editableDamage = power.manual || !hasAttack;
                const damageSource = critical
                    ? (criticalPower !== null ? String(criticalPower) : '【要害威力最大值】')
                    : power.expression;
                const powerTerm = buildPowerTerm(damageSource, stab, multiplier);
                let attackTerm = attackMod;
                if (hasAttack && multiplier === 4) attackTerm *= 2;
                if (hasAttack && multiplier === 0.25) attackTerm = attackTerm >= 0
                    ? Math.floor(attackTerm / 2) : Math.ceil(attackTerm / 2);
                let expression = powerTerm + (hasAttack ? formatModifier(attackTerm) : '+【攻方调整】');
                if (defenseValue !== null) expression += formatModifier(-defenseValue);
                damageRollCommand = `.r${expression}`;
                lines.push(`${editableDamage ? '伤害骰模板' : '伤害骰'}：${damageRollCommand}`);
                const details = [`威力${move.damage}`];
                if (critical && criticalPower !== null) details.push(`要害取最大${criticalPower}`);
                if (stab) details.push('本系加成+3');
                if (hasAttack) details.push(`${attackLabel}调整${attackMod >= 0 ? '+' : ''}${attackMod}`);
                else {
                    const adjustment = multiplier === 4 ? '，并按双重克制翻倍' : multiplier === 0.25 ? '，并按双重抵抗减半后向0取整' : '';
                    lines.push(`攻方调整：请填写${attackLabel}调整值${adjustment}。`);
                }
                if (power.notes.length) lines.push(power.notes.join('；') + '。');
                if (critical && criticalPower === null) lines.push('要害威力最大值：先确定本次威力骰，再填写这些骰子的最大合计；本系与攻防修正已在模板中另列。');
                if (defenseValue !== null) details.push(`目标${defenseLabel}${defenseValue >= 0 ? '+' : ''}${defenseValue}`);
                lines.push(`组成：${details.join('，')}`);
                if (defenseValue === null) {
                    lines.push(`当前骰式尚未扣除目标${expectedDefense}调整；知道数值后在末尾补“${expectedDefense}N”。`);
                    lines.push(`例如：.宝可梦伤害 ${pokemon.name || pokemon.species} ${targetTypes.join('/')} ${move.name} ${expectedDefense}1`);
                } else if (defenseLabel !== expectedDefense) {
                    lines.push(`提醒：${category}招式通常扣目标${expectedDefense}，你填写的是${defenseLabel}。`);
                }
                if (multiplier !== 1) {
                    lines.push('每个被翻倍或减半的部分若只产生不足3点的影响，按规则修正为至少±3点。');
                }
                if (critical) {
                    lines.push('要害还会把攻方不利的攻击/特攻阶级与目标有利的防御/特防阶级按0级处理，并无视墙类效果。');
                }
                lines.push('最终伤害最低为1；能力阶级、特性、道具、天气等临场修正需另行增减。');
            }
        }
        if (editableDamage) lines.push('填写方法：把模板内的【文字】替换为对应数值或骰式，再发送。官方QQ可点“填写伤害骰”放入输入框修改，按钮不会自动发送。');
        if (move.effect) lines.push(`效果提示：${move.effect}`);
        return {
            text: lines.join('\n'), pokemon, move, targetTypes, multiplier,
            rollCommands: [
                hitCommand ? { label: '命中骰', data: hitCommand } : null,
                damageRollCommand ? { label: editableDamage ? '填写伤害骰' : '伤害骰', data: damageRollCommand } : null
            ].filter(Boolean)
        };
    };

    // ==========================================
    // 名片刷新
    // ==========================================
    const refreshNameCard = (mctx) => {
        const playerId = mctx.player.userId;
        const trainerData = getTrainerData(mctx);

        const hp = getStoredValue(trainerData, "hp");
        const hpMax = getStoredValue(trainerData, "hpmax");
        const travel = getStoredValue(trainerData, "旅行点");
        const supply = getStoredValue(trainerData, "物资点");

        const rawName = seal.format(mctx, "{$t玩家_RAW}");
        let template = seal.ext.getStringConfig(ext, "训练家名片模板");
        if (!template || !template.trim()) {
            template = "{name} HP{hp}/{hpmax} TP{旅行点} IP{物资点}";
        }

        const cardText = template
            .replace(/\{name\}/g, rawName)
            .replace(/\{hp\}/g, String(hp))
            .replace(/\{hpmax\}/g, String(hpMax))
            .replace(/\{旅行点\}/g, String(travel))
            .replace(/\{物资点\}/g, String(supply));

        try {
            seal.setPlayerGroupCard(mctx, cardText);
            return cardText;
        } catch (e) {
            console.error("刷新名片失败", e);
            return null;
        }
    };

    // ==========================================
    // 数据持久化
    // ==========================================
    let playerData = {};
    try {
        let dataStr = ext.storageGet('pokemon_player_data');
        if (!dataStr && migrationExt) {
            dataStr = migrationExt.storageGet('pokemon_player_data');
            if (dataStr) ext.storageSet('pokemon_player_data', dataStr);
        }
        if (dataStr) playerData = JSON.parse(dataStr);
    } catch(e) {
        console.error('读取宝可梦玩家数据失败',e);
    }

    const saveData = (ctx, record) => {
        if (!isPkm(ctx)) {
            ext.storageSet('pokemon_player_data', JSON.stringify(playerData));
            return;
        }
        const patch = Object.assign({}, record.trainer);
        patch[PKM_DATA] = JSON.stringify({ schema: 1, pokemon: record.pokemon, meta: record.meta });
        seal.character.patchCurrent(ctx, record.cardId, PKM_RULE, JSON.stringify(patch));
    };

    // 一键录卡使用的稳定接口。直接复用本插件的内存存档和持久化函数，
    // 避免在官方 QQ 等适配器中通过伪造 CmdArgs 间接调用 .pst 时写错玩家。
    ext.autocardApiV1 = {
        importTrainer: (ctx, rawValues) => {
            if (!ctx || !ctx.player || !ctx.player.userId) {
                throw new Error('一键录卡没有取得当前玩家标识');
            }
            const playerId = String(ctx.player.userId);
            const record = getRecord(ctx);
            const trainerData = record.trainer;
            const values = rawValues && typeof rawValues === 'object' ? rawValues : {};
            const nonNegativeAttrs = new Set(['hp', 'hpmax', '旅行点', '物资点']);
            let count = 0;
            Object.keys(values).forEach(rawName => {
                const number = Number(values[rawName]);
                if (!Number.isFinite(number)) return;
                const attrName = normalizeAttrName(String(rawName));
                const value = Math.trunc(number);
                trainerData[attrName] = nonNegativeAttrs.has(attrName) ? Math.max(0, value) : value;
                count += 1;
            });
            if (count > 0) saveData(ctx, record);
            let cardText = '';
            try { cardText = refreshNameCard(ctx) || ''; } catch (_) {}
            return { count, playerId, cardText, trainer: Object.assign({}, trainerData) };
        },
        readTrainer: ctx => {
            if (!ctx || !ctx.player || !ctx.player.userId) return {};
            return Object.assign({}, getTrainerData(ctx));
        },
        importRoster: (ctx, rawPokemon) => {
            if (!ctx || !ctx.player || !ctx.player.userId) {
                throw new Error('一键录卡没有取得当前玩家标识');
            }
            const playerId = String(ctx.player.userId);
            const roster = (Array.isArray(rawPokemon) ? rawPokemon : [])
                .map(sanitizePokemon)
                .filter(pokemon => pokemon.name || pokemon.species);
            const record = getRecord(ctx);
            record.pokemon = roster;
            record.meta.rosterImportedAt = Date.now();
            saveData(ctx, record);
            return { count: roster.length, playerId, pokemon: JSON.parse(JSON.stringify(roster)) };
        },
        readRoster: ctx => {
            if (!ctx || !ctx.player || !ctx.player.userId) return [];
            const roster = getRecord(ctx).pokemon;
            return JSON.parse(JSON.stringify(Array.isArray(roster) ? roster : []));
        }
    };

    // ==========================================
    // 指令绑定
    // ==========================================
    const createCmd = (name, help, solve, allowDelegate=false) => {
        const cmd = seal.ext.newCmdItemInfo();
        cmd.name = name;
        cmd.help = help;
        cmd.allowDelegate = allowDelegate;
        cmd.solve = (ctx, msg, args) => {
            // The import bridge must propagate errors so auto-import never
            // reports success after a refused write.
            if (name === 'autocard_import_v1') return solve(ctx, msg, args);
            try { return solve(ctx, msg, args); }
            catch (error) {
                seal.replyToSender(ctx, msg, String(error && error.message || error));
                return seal.ext.newCmdExecuteResult(true);
            }
        };
        return cmd;
    };

    const handlePmCore = (ctx, msg, cmdArgs, forcedText='') => {
        const mctx = (cmdArgs && seal.getCtxProxyFirst) ? seal.getCtxProxyFirst(ctx, cmdArgs) : ctx;
        const pmText = forcedText || getCommandInputText(msg, cmdArgs, 'pm', 1);

        if (!pmText || pmText.toLowerCase() === 'help') {
            seal.replyToSender(ctx, msg, HELP_CHECK);
            return seal.ext.newCmdExecuteResult(true);
        }

        const parsed = parsePmRequest(pmText);
        if (!parsed.ok) {
            seal.replyToSender(ctx, msg, `检定格式错误：${pmText}\n${parsed.reason}`);
            return seal.ext.newCmdExecuteResult(true);
        }

        const playerName = seal.format(mctx, "{$t玩家}");

        if (parsed.type === 'dice') {
            const lines = [];
            for (let i = 0; i < parsed.repeat; i++) {
                lines.push(buildDiceCheckLine(parsed));
            }

            const header = parsed.repeat === 1 ? '自定义检定: ' : `${parsed.repeat} 次自定义检定：`;
            seal.replyToSender(ctx, msg, buildRepeatedResultText(playerName, header, lines));
            return seal.ext.newCmdExecuteResult(true);
        }

        if (parsed.type === 'skill') {
            const playerId = mctx.player.userId;
            const trainerData = getTrainerData(mctx);
            const canonicalSkillName = normalizeAttrName(parsed.skillName);

            if (!hasStoredValue(trainerData, canonicalSkillName)) {
                seal.replyToSender(ctx, msg, `未找到 ${playerName} 技能 "${parsed.skillName}" 的数据，请先使用 .pst 导入。`);
                return seal.ext.newCmdExecuteResult(true);
            }

            const skillValue = getStoredValue(trainerData, canonicalSkillName);
            const lines = [];
            for (let i = 0; i < parsed.repeat; i++) {
                lines.push(buildSkillCheckLine(canonicalSkillName, skillValue, parsed.tempModifier, parsed.mode));
            }

            const header = parsed.repeat === 1 ? '' : `${parsed.repeat} 次${canonicalSkillName}检定：`;
            seal.replyToSender(ctx, msg, buildRepeatedResultText(playerName, header, lines));
            return seal.ext.newCmdExecuteResult(true);
        }

        seal.replyToSender(ctx, msg, `检定格式错误：${pmText}\n未能识别这条 .pm 指令。`);
        return seal.ext.newCmdExecuteResult(true);
    };

    // 一键录卡的跨扩展命令桥。SealDice 管理的 cmdMap 可以跨 Goja
    // 运行域调用，而挂在 ext 上的普通 JS 自定义属性在部分核心版本中
    // 不可见。该命令只接受一键录卡构造的内部 CmdArgs，不向群内回复。
    ext.cmdMap['autocard_import_v1'] = createCmd(
        'autocard_import_v1',
        '一键录卡内部桥接指令。',
        (ctx, msg, cmdArgs) => {
            if (!cmdArgs) return seal.ext.newCmdExecuteResult(false);
            const mctx = seal.getCtxProxyFirst ? seal.getCtxProxyFirst(ctx, cmdArgs) : ctx;
            if (!mctx || !mctx.player || !mctx.player.userId) {
                throw new Error('一键录卡没有取得当前玩家标识');
            }
            const raw = String(cmdArgs.rawArgs || cmdArgs.cleanArgs ||
                (cmdArgs.getArgN ? cmdArgs.getArgN(1) : '') || '').trim();
            const payload = JSON.parse(raw);
            if (cmdArgs.autocardInternal !== true &&
                (!payload || payload.protocol !== 'sealdice-autocard-v1')) {
                return seal.ext.newCmdExecuteResult(false);
            }
            if (payload.storage === 'native-pc-v1') {
                const card = requireCard(mctx);
                if (card.id !== payload.expectedCardId) throw new Error('生成卡图期间切换了角色卡，请确认目标角色后重新发送 .一键录卡 同意。');
            }
            const values = payload && payload.trainer && typeof payload.trainer === 'object'
                ? payload.trainer : {};
            const playerId = String(mctx.player.userId);
            const record = getRecord(mctx);
            const trainerData = record.trainer;
            const nonNegativeAttrs = new Set(['hp', 'hpmax', '旅行点', '物资点']);
            let count = 0;
            Object.keys(values).forEach(rawName => {
                const number = Number(values[rawName]);
                if (!Number.isFinite(number)) return;
                const attrName = normalizeAttrName(String(rawName));
                const value = Math.trunc(number);
                trainerData[attrName] = nonNegativeAttrs.has(attrName) ? Math.max(0, value) : value;
                count += 1;
            });
            const roster = (Array.isArray(payload && payload.pokemon) ? payload.pokemon : [])
                .map(sanitizePokemon)
                .filter(pokemon => pokemon.name || pokemon.species);
            record.pokemon = roster;
            record.meta.rosterImportedAt = Date.now();
            record.meta.autocardBridgeVersion = 1;
            saveData(mctx, record);
            try { refreshNameCard(mctx); } catch (_) {}
            return seal.ext.newCmdExecuteResult(count > 0 || roster.length > 0);
        },
        false
    );

    // --- .pst ---
    ext.cmdMap['pst'] = createCmd(
        'pst',
        '输入 .pst help 查看分段帮助。',
        (ctx,msg,cmdArgs)=>{
            const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);
            const pstText = getArgsText(cmdArgs, 1);

            if (!pstText) {
                seal.replyToSender(ctx, msg, HELP_INDEX);
                return seal.ext.newCmdExecuteResult(true);
            }

            const parts = pstText.split(/\s+/);
            if (parts[0].toLowerCase() === 'help') {
                const topic = parts.slice(1).join(' ');
                seal.replyToSender(ctx, msg, getHelpText(topic));
                return seal.ext.newCmdExecuteResult(true);
            }

            const playerId = mctx.player.userId;
            const playerName = seal.format(mctx, "{$t玩家}");
            const record = getRecord(mctx);
            const trainerData = record.trainer;

            const entries = parsePstEntries(pstText);
            let count = 0;

            const nonNegativeAttrs = ["hp", "hpmax", "旅行点", "物资点"];

            for (const entry of entries) {
                const attrName = entry.attrName;
                const rawValStr = entry.rawValStr;
                const val = entry.value;
                const currentVal = trainerData[attrName] || 0;

                if (rawValStr.startsWith('+')) {
                    trainerData[attrName] = currentVal + val;
                } else if (nonNegativeAttrs.includes(attrName) && val < 0) {
                    trainerData[attrName] = Math.max(0, currentVal + val);
                } else {
                    trainerData[attrName] = val;
                }
                count++;
            }

            if (count > 0) {
                saveData(mctx, record);
                const cardText = refreshNameCard(mctx);
                if (cardText) {
                    seal.replyToSender(ctx, msg, `已成功为 ${playerName} 录入/更新 ${count} 项属性/技能，并已刷新名片：\n${cardText}`);
                } else {
                    seal.replyToSender(ctx, msg, `已成功为 ${playerName} 录入/更新 ${count} 项属性/技能，但名片刷新失败。`);
                }
            } else {
                seal.replyToSender(ctx, msg, `未识别到任何属性和数值，请检查输入格式。\n输入 .pst help 查看帮助。`);
            }

            return seal.ext.newCmdExecuteResult(true);
        },
        true
    );

    // --- .pm ---
    ext.cmdMap['pm'] = createCmd(
        'pm',
        '技能检定 / 自定义掷骰。输入 .pst help 检定 查看说明。',
        (ctx,msg,cmdArgs)=>handlePmCore(ctx, msg, cmdArgs, ''),
        true
    );

    // --- .th ---
    ext.cmdMap['th'] = createCmd(
        'th',
        '手动刷新名片。输入 .pst help 名片 查看说明。',
        (ctx,msg,cmdArgs)=>{
            const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);
            const argsText = getArgsText(cmdArgs, 1);

            if (argsText.toLowerCase() === 'help') {
                seal.replyToSender(ctx, msg, HELP_CARD);
                return seal.ext.newCmdExecuteResult(true);
            }

            const playerId = mctx.player.userId;
            const playerName = seal.format(mctx, "{$t玩家}");

            const record = getRecord(mctx);
            if (!record || !record.trainer || Object.keys(record.trainer).length === 0) {
                seal.replyToSender(ctx, msg, `未找到 ${playerName} 的插件数据，请先使用 .pst 录卡。`);
                return seal.ext.newCmdExecuteResult(true);
            }

            const cardText = refreshNameCard(mctx);
            if (cardText) {
                seal.replyToSender(ctx, msg, `已为 ${playerName} 刷新名片：\n${cardText}`);
            } else {
                seal.replyToSender(ctx, msg, `已找到 ${playerName} 的数据，但刷新名片失败。`);
            }
            return seal.ext.newCmdExecuteResult(true);
        },
        true
    );

    ext.cmdMap['宝可梦迁移'] = createCmd('宝可梦迁移',
        '将旧插件中的训练家和队伍复制到当前空白旅伴角色卡；保留旧数据。',
        (ctx, msg, args) => {
            const mctx = seal.getCtxProxyFirst ? seal.getCtxProxyFirst(ctx, args) : ctx;
            const card = requireCard(mctx);
            const current = getRecord(mctx);
            if (Object.keys(current.trainer).length || (card.strings || {})[PKM_DATA]) {
                throw new Error('当前角色卡已有数据，已停止迁移。请新建一张空白旅伴卡后再操作。');
            }
            let sourceId = String(mctx.player.userId);
            if (!playerData[sourceId] && seal.identity && seal.identity.canonicalUserId) {
                sourceId = String(seal.identity.canonicalUserId(mctx) || sourceId);
            }
            if (!playerData[sourceId]) throw new Error('没有找到这个账号的旧宝可梦数据，请上传原表格重新导入。');
            const legacy = ensureLegacyRecord(sourceId);
            if (!Object.keys(legacy.trainer).length && !legacy.pokemon.length) throw new Error('旧宝可梦档案为空。');
            if (legacy.meta.nativeMigrationCardId) throw new Error('旧数据已经迁移过，请用 .pc list 和 .pc tag 切换到已迁移的卡。原始表格仍可重新导入新卡。');
            const migrated = JSON.parse(JSON.stringify(legacy));
            migrated.cardId = card.id;
            migrated.meta.migratedAt = Date.now();
            saveData(mctx, migrated);
            legacy.meta.nativeMigrationCardId = card.id;
            ext.storageSet('pokemon_player_data', JSON.stringify(playerData));
            seal.replyToSender(ctx, msg, '已将旧训练家和 ' + migrated.pokemon.length + ' 只宝可梦迁入【' + card.name + '】。旧插件数据仍保留。今后用 .pc new 新建角色，用 .pc tag 切换；队伍和伤害骰跟随当前角色卡。');
            return seal.ext.newCmdExecuteResult(true);
        });

    // Use the supported pre-parser hook, since native COC .ra otherwise wins
    // command lookup. Rewrite both modern segments and legacy message text.
    ext.onMessageReceived = (ctx, msg) => {
        if (!msg || !isPkm(ctx)) return;
        const convert = text => String(text || '').replace(
            /^(\s*(?:\[CQ:at,[^\]]+\]\s*)*[.。!！/／])ra(?=\s|[\u3400-\u9fff]|\d|$)/i, '$1pm');
        msg.message = convert(msg.message);
        const segments = Array.from(msg.segment || []).filter(s => typeof s.content === 'string');
        const joined = segments.map(s => s.content).join('');
        if (segments.length && convert(joined) !== joined) {
            segments[0].content = convert(joined);
            segments.slice(1).forEach(s => { s.content = ''; });
        }
    };

    // --- .宝可梦队伍 ---
    ext.cmdMap['宝可梦队伍'] = createCmd(
        '宝可梦队伍',
        '查看智能录卡保存的宝可梦和招式。',
        (ctx, msg, cmdArgs) => {
            const mctx = seal.getCtxProxyFirst ? seal.getCtxProxyFirst(ctx, cmdArgs) : ctx;
            const playerId = mctx && mctx.player ? String(mctx.player.userId || '') : '';
            const roster = playerId ? getRecord(mctx).pokemon : [];
            if (!Array.isArray(roster) || !roster.length) {
                seal.replyToSender(ctx, msg,
                    '还没有录入宝可梦队伍。请先上传旅绊角色卡，再发送 .一键录卡 导入 最新 和 .一键录卡 同意。');
                return seal.ext.newCmdExecuteResult(true);
            }
            const lines = ['【已录入的宝可梦队伍】'];
            roster.forEach((pokemon, index) => {
                const displayName = pokemon.name || pokemon.species || `宝可梦${index + 1}`;
                const species = pokemon.species && pokemon.species !== displayName ? `（${pokemon.species}）` : '';
                const types = (pokemon.types || []).join('/') || '属性未填';
                const moves = (pokemon.moves || []).map(move => move.name).filter(Boolean).join('、') || '暂无招式';
                lines.push(`${index + 1}. ${displayName}${species}｜${types}`);
                lines.push(`   招式：${moves}`);
            });
            lines.push('伤害指引：.宝可梦伤害 <昵称或种族> <目标属性/第二属性> <招式> [防御N或特防N]');
            seal.replyToSender(ctx, msg, lines.join('\n'));
            return seal.ext.newCmdExecuteResult(true);
        },
        true
    );

    // --- .宝可梦伤害 / .伤害骰 / .pkdmg ---
    const damageCommand = createCmd(
        '宝可梦伤害',
        '根据已录入队伍、目标属性和招式生成命中骰与伤害骰。',
        (ctx, msg, cmdArgs) => {
            const mctx = seal.getCtxProxyFirst ? seal.getCtxProxyFirst(ctx, cmdArgs) : ctx;
            const playerId = mctx && mctx.player ? String(mctx.player.userId || '') : '';
            const roster = playerId ? getRecord(mctx).pokemon : [];
            if (!Array.isArray(roster) || !roster.length) {
                seal.replyToSender(ctx, msg,
                    '还没有录入宝可梦队伍。请先上传旅绊角色卡并完成一键录卡。');
                return seal.ext.newCmdExecuteResult(true);
            }
            const result = buildDamageGuide(roster, getArgsText(cmdArgs, 1));
            if (result.help) seal.replyToSender(ctx, msg, HELP_DAMAGE);
            else if (result.error) seal.replyToSender(ctx, msg, `无法生成骰式：${result.error}\n\n${HELP_DAMAGE}`);
            else {
                const marker = isOfficialQQContext(ctx, msg) ? buildOfficialQQInputButtonsMarker(result.rollCommands) : '';
                seal.replyToSender(ctx, msg, result.text + (marker ? '\n' + marker : ''));
            }
            return seal.ext.newCmdExecuteResult(true);
        },
        true
    );
    ext.cmdMap['宝可梦伤害'] = damageCommand;
    ext.cmdMap['伤害骰'] = damageCommand;
    ext.cmdMap['pkdmg'] = damageCommand;

    // --- .xlj / .训练家 ---
    ext.cmdMap['xlj'] = ext.cmdMap['训练家'] = createCmd(
        'xlj',
        '自由属性池生成。输入 .pst help 生成 查看说明。',
        (ctx,msg,cmdArgs)=>{
            const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);
            const argsText = getArgsText(cmdArgs, 1);
            const val = argsText.split(/\s+/)[0];

            if (val === 'help') {
                seal.replyToSender(ctx, msg, HELP_GEN);
                return seal.ext.newCmdExecuteResult(true);
            }

            let count = Math.min(parseInt(val)||1, MAX_GROUPS);
            const playerName = seal.format(mctx,"{$t玩家}");
            const result = `${playerName} 的自由属性池：\n\n` + generateStatGroups(count,false) + `\n\n(请自由分配至：${ATTRIBUTES.join('、')})`;
            seal.replyToSender(ctx,msg,result);
            return seal.ext.newCmdExecuteResult(true);
        },
        true
    );

    // --- .xljx / .训练家x ---
    ext.cmdMap['xljx'] = ext.cmdMap['训练家x'] = createCmd(
        'xljx',
        '固定能力值生成。输入 .pst help 生成 查看说明。',
        (ctx,msg,cmdArgs)=>{
            const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);
            const argsText = getArgsText(cmdArgs, 1);
            const val = argsText.split(/\s+/)[0];

            if (val === 'help') {
                seal.replyToSender(ctx, msg, HELP_GEN);
                return seal.ext.newCmdExecuteResult(true);
            }

            let count = Math.min(parseInt(val)||1, MAX_GROUPS);
            const playerName = seal.format(mctx,"{$t玩家}");
            const result = `${playerName} 的固定能力值：\n\n` + generateStatGroups(count,true);
            seal.replyToSender(ctx,msg,result);
            return seal.ext.newCmdExecuteResult(true);
        },
        true
    );

    // ==========================================
    // 黏连写法兜底拦截
    // 尝试兼容：
    // .pm1d20+3
    // .pmd20+1
    // .pmd +2
    // .pm优势
    // .pm探查
    // .pm3#优势探查-1
    // ==========================================
    ext.onNotCommandReceived = (ctx, msg) => {
        const raw = getRawMessageText(msg);
        if (!raw) return;

        const stickyPmText = extractStickyPmText(msg);
        if (stickyPmText !== null && stickyPmText !== undefined && /^[\.。／/]pm/i.test(raw)) {
            handlePmCore(ctx, msg, null, stickyPmText);
            return;
        }
    };

    // ==========================================
    // 数据区（统一收拢到文件末尾，便于维护与手改）
    // ==========================================
    const MAX_GROUPS = 20;
    const CARD_V13_EMPTY_SKILL_NAMES = new Set(['分支', '分支①', '分支②', '分支1', '分支2']);
    const ATTRIBUTES = ["力量", "体魄", "智识", "意念", "机敏", "魅力", "幸运"];
    const SPECIAL_STATS = {18:"闪光（18）", 19:"觉醒（19）", 20:"共鸣（20）"};
    const TYPE_ALIASES = {
        '一般':'一般', '普通':'一般', 'normal':'一般',
        '格斗':'格斗', '斗':'格斗', 'fighting':'格斗',
        '飞行':'飞行', '飞':'飞行', 'flying':'飞行',
        '毒':'毒', 'poison':'毒',
        '地面':'地面', '地':'地面', 'ground':'地面',
        '岩石':'岩石', '岩':'岩石', 'rock':'岩石',
        '虫':'虫', 'bug':'虫',
        '幽灵':'幽灵', '鬼':'幽灵', 'ghost':'幽灵',
        '钢':'钢', 'steel':'钢',
        '火':'火', 'fire':'火',
        '水':'水', 'water':'水',
        '草':'草', 'grass':'草',
        '电':'电', '雷':'电', 'electric':'电',
        '超能力':'超能力', '超能':'超能力', '超':'超能力', 'psychic':'超能力',
        '冰':'冰', 'ice':'冰',
        '龙':'龙', 'dragon':'龙',
        '恶':'恶', 'dark':'恶',
        '妖精':'妖精', '妖':'妖精', 'fairy':'妖精'
    };
    const TYPE_CHART = {
        '一般': {'岩石':0.5, '幽灵':0, '钢':0.5},
        '格斗': {'一般':2, '飞行':0.5, '毒':0.5, '岩石':2, '虫':0.5, '幽灵':0, '钢':2, '超能力':0.5, '冰':2, '恶':2, '妖精':0.5},
        '飞行': {'格斗':2, '岩石':0.5, '虫':2, '钢':0.5, '草':2, '电':0.5},
        '毒': {'毒':0.5, '地面':0.5, '岩石':0.5, '幽灵':0.5, '钢':0, '草':2, '妖精':2},
        '地面': {'飞行':0, '毒':2, '岩石':2, '虫':0.5, '钢':2, '火':2, '草':0.5, '电':2},
        '岩石': {'格斗':0.5, '飞行':2, '地面':0.5, '虫':2, '钢':0.5, '火':2, '冰':2},
        '虫': {'格斗':0.5, '飞行':0.5, '毒':0.5, '幽灵':0.5, '钢':0.5, '火':0.5, '草':2, '超能力':2, '恶':2, '妖精':0.5},
        '幽灵': {'一般':0, '幽灵':2, '超能力':2, '恶':0.5},
        '钢': {'岩石':2, '钢':0.5, '火':0.5, '水':0.5, '电':0.5, '冰':2, '妖精':2},
        '火': {'岩石':0.5, '虫':2, '钢':2, '火':0.5, '水':0.5, '草':2, '冰':2, '龙':0.5},
        '水': {'地面':2, '岩石':2, '火':2, '水':0.5, '草':0.5, '龙':0.5},
        '草': {'飞行':0.5, '毒':0.5, '地面':2, '岩石':2, '虫':0.5, '钢':0.5, '火':0.5, '水':2, '草':0.5, '龙':0.5},
        '电': {'飞行':2, '地面':0, '水':2, '草':0.5, '电':0.5, '龙':0.5},
        '超能力': {'格斗':2, '毒':2, '钢':0.5, '超能力':0.5, '恶':0},
        '冰': {'飞行':2, '地面':2, '钢':0.5, '火':0.5, '水':0.5, '草':2, '冰':0.5, '龙':2},
        '龙': {'钢':0.5, '龙':2, '妖精':0},
        '恶': {'格斗':0.5, '幽灵':2, '超能力':2, '恶':0.5, '妖精':0.5},
        '妖精': {'格斗':2, '毒':0.5, '钢':0.5, '火':0.5, '龙':2, '恶':2}
    };

    // ==========================================
    // 分段帮助文案
    // ==========================================
    const HELP_INDEX = `【门版宝可梦TRPG综合助手帮助】

你现在最常用的指令：
1. .pst 录卡/改值
2. .pm 技能检定 / 自定义掷骰
3. .sn pkm 自动旅伴名片（也可 .sn 旅伴）；.th 手动刷新名片
4. .宝可梦队伍 查看智能录卡保存的队伍
5. .宝可梦伤害 生成命中骰和伤害骰
6. .xlj / .xljx 生成功能
7. .set pkm 后 .pc new 角色名：创建原生旅伴卡
8. .pc tag 角色名：切换训练家、技能与队伍
9. .宝可梦迁移：把旧插件数据迁到当前空白旅伴卡

.sn pkm 显示：角色名 HP当前/上限 TP旅行点 IP物资点。
.sn none 只显示角色名；.sn off 关闭自动名片。
角色卡改名用 .pc rename 新名字；.sn 只设置名片显示格式。

旅伴规则下 .ra 技能 与 .pm 技能 相同，使用 D20 + 已导入调整值。
每个角色的数据独立保存。新建卡不会复制旧队伍。

查看分段说明：
.pst help 录卡
.pst help 检定
.pst help 名片
.pst help 生成
.pst help 代操
.pst help 伤害
`;

    const HELP_TEAM = `【宝可梦队伍】

.宝可梦队伍
旅伴规则下查看当前 .pc 角色卡的宝可梦、属性与招式。

如果没有数据：
先上传旅绊角色卡，再发送：
.一键录卡 导入 最新
.一键录卡 同意`;

    const HELP_DAMAGE = `【宝可梦命中与伤害骰】

基础格式：
.宝可梦伤害 <宝可梦昵称或种族> <目标属性> <招式名>

双属性用 / 连接：
.宝可梦伤害 皮卡丘 水/飞行 电光

知道目标闪避、防御调整时可一起填写：
.宝可梦伤害 皮卡丘 水/飞行 电光 闪避6 防御1
.宝可梦伤害 皮卡丘 草/毒 电网 闪避7 特防2

自然20击中要害时：
.宝可梦伤害 皮卡丘 水/飞行 电光 防御1 要害

组合骰（如信号光束的2D4+1D6）会直接生成完整骰式。
XD4、2DX、条件威力或固定伤害会给出带【文字】的可编辑模板。
把【文字】换成数值或骰式后再发送；官方QQ点“填写伤害骰”可放入输入框，按钮不会自动发送。

别名：.伤害骰、.pkdmg
查看队伍：.宝可梦队伍

说明：物理招式扣防御，特殊招式扣特防；没有填写目标调整值时，会先给出尚未扣防御的攻击侧骰式。EP只作提示，不会被本指令自动扣除。`;

    const HELP_RECORD = `【.pst 录卡说明】

基础格式：
.pst 属性名数值属性名数值
也可以写成：
.pst 属性名 数值 属性名 数值

示例：
.pst hpmax30hp30旅行点3物资点10力量-2体魄-1智识2意念0机敏1魅力5幸运0探查2采集-3
.pst hpmax30hp30旅行点3物资点10力气-2体魄-1智识2意念0机敏1魅力5幸运0
.pst TP3 IP10
.pst tp+1 ip-2

数值规则：
1. 直接正数：直接设定
   例：.pst 旅行点10

2. 带 + ：在当前值基础上增加
   例：.pst 旅行点+2

3. 对 hp / hpmax / 旅行点 / 物资点
   写负数时按“当前值减少”，且不会低于 0
   例：.pst hp-1
       .pst 物资点-2

4. 对其他属性或技能
   写负数时按“直接设为负值”
   例：.pst 力量-2
       .pst 力气-2（新版卡写法，与力量相同）

补充：
hp / HP / Hp / hP 都会被识别为 hp
hpmax / HPMAX / HPmax / hPmAx 都会被识别为 hpmax
tp / TP / Tp / tP 都会被识别为 旅行点
ip / IP / Ip / iP 都会被识别为 物资点
知识 会自动按 智识 处理

空白卡 v1.3：
1. 可直接复制“训练家”页右侧导入板块生成的整行 .pst 指令发送。
2. 当前HP留空时，会按HP上限导入；不会再漏掉当前HP。
3. 尚未选择的“分支① / 分支② / 分支”占位项会自动忽略。

其他说明：
.pst help 检定
.pst help 名片
.pst help 生成
.pst help 代操`;

    const HELP_CHECK = `【.pm 检定说明】

技能检定：
.pm 妙手
.pm 探查+2
.pm 妙手-1
.pm 劣势探查
.pm 优势妙手-1

多次技能检定：
.pm 3#探查
.pm 3#优势探查
.pm 3#劣势探查-1

自定义骰式：
.pm 1d20+3
.pm d20+1
.pm d
.pm +2
.pm 2d6+3
.pm 3d10
.pm d100

多次自定义骰式：
.pm 3#1d20+2
.pm 3#优势+1

黏连写法（尽量兼容）：
.pm1d20+3
.pmd20+1
.pmd +2
.pm优势
.pm探查
.pm3#优势探查-1

说明：
1. 输入技能名时，自动读取你之前 .pst 保存的数据
2. 输入骰表达式时，按“自定义掷骰”处理
3. 支持 NdM±K，例如 2d6+3、3d10、d100
4. 省略 N 时默认为 1；省略 M 时默认为 20
5. 所以 d = 1d20，d+2 = 1d20+2，+2 = 1d20+2
6. 优势/劣势 目前只支持 d20 系检定
7. 支持 技能名±修正、优势/劣势+技能名±修正、N#重复检定
8. “知识”会自动按“智识”处理

其他说明：
.pst help 录卡
.pst help 名片
.pst help 代操`;

    const HELP_CARD = `【旅伴名片：.sn pkm / .th】

自动名片：.sn pkm（也可 .sn 旅伴）
读取当前绑定角色卡，显示角色名、HP、旅行点和物资点。
.sn none 只显示角色名；.sn off 关闭自动名片。
角色卡本身改名：.pc rename 新名字

1. 每次 .pst 成功后，插件会自动刷新群名片
2. 若想手动刷新，请输入：
   .th

名片默认格式：
玩家名 HP当前/上限 TP旅行点 IP物资点

插件设置里的“训练家名片模板”用于 .th / .pst 刷新。
.sn pkm 使用核心旅伴格式，自设格式可用 .sn expr。

其他说明：
.pst help 录卡
.pst help 检定
.pst help 代操`;

    const HELP_GEN = `【生成指令说明】

1. 自由属性池：
.xlj
.xlj 3

2. 固定能力值：
.xljx
.xljx 2

说明：
1. .xlj 会生成可自由分配的 7 项能力值。
2. .xljx 会按 力量、体魄、智识、意念、机敏、魅力、幸运 固定列出。
3. 本精简版已移除 .pkm / 宝可梦 / 宝可梦作成 指令；随机宝可梦请改用牌堆处理。

其他说明：
.pst help 录卡
.pst help 代操`;

    const HELP_DELEGATE = `【@代操作说明】

以下指令支持 @某人：
.pst @某人 ...
.pm @某人 技能名
.pm @某人 探查+2
.pm @某人 3#优势探查-1
.pm @某人 d20+2
.pm @某人 优势
.th @某人
.xlj @某人 3
.xljx @某人 2
示例：
.pst @小明 hp-1
.pm @小明 探查
.pm @小明 妙手-1
.pm @小明 3#优势探查+2
.th @小明

其他说明：
.pst help 录卡
.pst help 检定
.pst help 生成`;

    // ==========================================
    // 属性别名与规范化
    // ==========================================
    const ATTR_ALIASES = {
        "hp": ["hp", "HP", "Hp", "hP", "当前HP", "当前hp", "体力", "生命"],
        "hpmax": ["hpmax", "HPMAX", "HPmax", "Hpmax", "hPmax", "hpMax", "最大HP", "HP上限", "生命上限"],
        "旅行点": ["旅行点", "TP", "tp", "Tp", "tP"],
        "物资点": ["物资点", "IP", "ip", "Ip", "iP"],
        "智识": ["智识", "知识"],

        "力量": ["力量", "力气"],
        "体魄": ["体魄"],
        "意念": ["意念"],
        "机敏": ["机敏"],
        "魅力": ["魅力"],
        "幸运": ["幸运"],

        "探查": ["探查"],
        "采集": ["采集"],
        "矿物": ["矿物"],
        "植物": ["植物"],
        "传说": ["传说"],
        "宝可梦": ["宝可梦"],
        "制球": ["制球"],
        "制香": ["制香"],
        "制药": ["制药"],
        "锻造": ["锻造"],
        "医疗": ["医疗"],
        "机械": ["机械"],
        "垂钓": ["垂钓"],
        "驾驶": ["驾驶"],
        "烹调": ["烹调"],
        "运动": ["运动"],
        "对战": ["对战"],
        "协调": ["协调"],
        "骑乘": ["骑乘"],
        "表演": ["表演"],
        "声乐": ["声乐"],
        "舞蹈": ["舞蹈"],
        "绘画": ["绘画"],
        "写作": ["写作"],
        "格斗术": ["格斗术"],
        "忍术": ["忍术"],
        "超能力": ["超能力"],
        "魔术": ["魔术"],
        "潜伏": ["潜伏"],
        "妙手": ["妙手"],
        "话术": ["话术"],
        "战斗": ["战斗", "战斗术"],
        "武士道": ["武士道"]
    };

    const ALIAS_TO_CANONICAL = {};
    for (const canonical in ATTR_ALIASES) {
        for (const alias of ATTR_ALIASES[canonical]) {
            ALIAS_TO_CANONICAL[alias] = canonical;
            ALIAS_TO_CANONICAL[alias.toLowerCase()] = canonical;
        }
    }

    if (seal.gameSystem && seal.gameSystem.newTemplateByYaml) {
        // JSON is valid YAML; this API honors the v2 template's YAML field names.
        seal.gameSystem.newTemplateByYaml(JSON.stringify({
            name: PKM_RULE, fullName: '宝可梦旅伴规则', authors: ['SNOM'],
            version: '1.0.1', templateVer: '2.0', updatedTime: '20260914',
            attrs: { defaults: {}, defaultsComputed: {} }, alias: ATTR_ALIASES,
            commands: {
                sn: Object.fromEntries(['pkm', 'pokemon', '旅伴', '旅绊', PKM_RULE].map(key => [key, {
                    template: '{$t玩家_RAW} HP{hp}/{hpmax} TP{旅行点} IP{物资点}',
                    helpText: '自动设置旅伴名片：角色名、生命值、旅行点、物资点'
                }])),
                set: { diceSides: '20', keys: ['pkm', 'pokemon', '旅伴', '旅绊', PKM_RULE],
                    relatedExt: ['coc7', '门版宝可梦TRPG综合助手v1.38.51'],
                    enableTip: '已切换旅伴规则，默认 D20。请用 .pc new 角色名 新建卡，或 .pc tag 角色名 切换已有旅伴卡；.ra/.pm 技能进行检定。' },
                st: { show: { top: ['hp', 'hpmax', '旅行点', '物资点'].concat(ATTRIBUTES),
                    ignores: [PKM_DATA, '$ver'], itemsPerLine: 4 } }
            }
        }));
    }

}
