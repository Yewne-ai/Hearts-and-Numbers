/* ============================================================
   于你 Yewne — 三数问心语料 v1
   对齐产品文档 §5.3 / §5.5 / §5.6 / §5.8 / §5.9

   本文件是「版本化语料」的 demo 形态。字段结构刻意贴近文档
   §5.9 建议的目录（palaces / positions / transitions / ...），
   技术团队可直接拆成对应的 JSON 资源。

   六宫配色说明（文档 §4.6 硬约束）：
   「六宫使用六组可区分的色彩与几何符号，但不把红色等同于凶、
     绿色等同于吉」
   —— 因此这里刻意把绿色给了「赤口」（摩擦），把红色给了
      「小吉」（小进展），主动打断颜色与吉凶的语义映射。
   ============================================================ */

export const METHOD_VERSION = 'xlr-six-palace-v1';
export const CORPUS_VERSION = '2026-08-v1';

/* ---------- 六宫基础语料（文档 §5.5） ---------- */
export const PALACES = [
  {
    id: 'daan', label: '大安', index: 0,
    color: '#2f6bff', tint: '#e8effe', symbol: 'circle',
    keywords: ['稳定', '安定', '守成'],
    neutral: '当前更需要稳定基础，不宜因焦虑强行加速',
    emotion: ['渴望确定', '控制', '安全感'],
    action: ['回到事实、作息、边界和已有支持'],
    forbidden: ['一定成功', '什么都不用做'],
    summary: '这件事现在更需要的是稳住，而不是加速。',
    micro: '写下这周你已经在稳定做的三件事，这几天先不加新的。',
    positions: {
      起势: '你会在这个时候问，可能是因为想把一件晃动的事重新放稳。这份想稳住的心情本身没有问题。',
      过程: '事情大致还在原来的轨道上。真正消耗你的，可能不是变化本身，而是怕它变。',
      当下: '现在更值得做的是回到具体的事实和日常节奏，而不是急着推动一个大动作。',
    },
  },
  {
    id: 'liulian', label: '留连', index: 1,
    color: '#8153f0', tint: '#f0eafe', symbol: 'rings',
    keywords: ['延迟', '反复', '牵绊'],
    neutral: '问题里可能有尚未结束或反复拉扯的部分',
    emotion: ['反刍', '等待', '舍不得', '未完成感'],
    action: ['找出最卡的一环', '为等待设置时间边界'],
    forbidden: ['永远不会有结果', '被小人缠住'],
    summary: '你难受的可能不是没有答案，而是它一直悬着。',
    micro: '写下你愿意等待的最晚时间，以及到时候要做的决定。',
    positions: {
      起势: '这件事大概已经在你心里转了不止一次。你现在问它，是因为它还没有真正结束。',
      过程: '里面可能有一段没说清、也没断掉的部分，让整件事一直悬在那里。',
      当下: '与其继续等一个答复，不如先找出最卡的那一环，并给等待设一个时间边界。',
    },
  },
  {
    id: 'suxi', label: '速喜', index: 2,
    color: '#ff6a3d', tint: '#ffe9e2', symbol: 'triangle',
    keywords: ['消息', '推动', '转机'],
    neutral: '事情可能正在出现变化，但变化不等于结果',
    emotion: ['希望', '急迫', '害怕错过'],
    action: ['做好准备', '验证消息', '避免过早下注'],
    forbidden: ['马上会复合', '录取已定'],
    summary: '有东西在动，但还没有落定，现在重要的是怎么接住它。',
    micro: '写下如果消息真的来了，你希望自己第一句话怎么说。',
    positions: {
      起势: '最近可能有什么在动。你问，是因为你察觉到了变化，又不确定它算不算数。',
      过程: '事情可能正在出现变化，但变化不等于结果，中间还有一段路要走。',
      当下: '可以做的是准备好如何回应，而不是提前把全部期待押在这一个信号上。',
    },
  },
  {
    id: 'chikou', label: '赤口', index: 3,
    color: '#17b57f', tint: '#dcf6ec', symbol: 'diamond',
    keywords: ['摩擦', '误解', '言语'],
    neutral: '沟通方式或防御状态可能比事件本身更关键',
    emotion: ['被冒犯', '委屈', '愤怒', '戒备'],
    action: ['放慢表达', '确认意图', '避免冲动对抗'],
    forbidden: ['必有争吵', '对方在害你'],
    summary: '真正卡住的可能不是这件事，而是你们说话的方式。',
    micro: '挑一句你最在意的话，写下它至少两种可能的意思。',
    positions: {
      起势: '你会在此刻提出来，可能是因为某句话、某个语气让你不太舒服。',
      过程: '比事情本身更关键的，可能是双方表达和防御的方式。',
      当下: '值得先放慢表达，把「我以为你的意思是」确认一遍，再决定要不要回应。',
    },
  },
  {
    id: 'xiaoji', label: '小吉', index: 4,
    color: '#ff5a6e', tint: '#ffe8ec', symbol: 'arc',
    keywords: ['小进展', '协作', '支持'],
    neutral: '可能有有限但真实的帮助或改善空间',
    emotion: ['松动', '愿意尝试', '需要支持'],
    action: ['接受小帮助', '先完成一小步'],
    forbidden: ['贵人必来', '事情必成'],
    summary: '事情没有全好，但确实有一处可以先动起来。',
    micro: '找一件今天就能完成的小事，先把它做完。',
    positions: {
      起势: '你问这件事，可能是因为你隐约感觉它还有松动的余地。',
      过程: '可能存在有限但真实的帮助或改善空间，只是它不够显眼。',
      当下: '可以先接受一个小的帮助，或者先完成一小步，不必等条件全部齐了再开始。',
    },
  },
  {
    id: 'kongwang', label: '空亡', index: 5,
    color: '#e5a417', tint: '#fdf3d7', symbol: 'square',
    keywords: ['信息不足', '落空', '悬置'],
    neutral: '当前可能缺少关键事实，或期待没有现实支撑',
    emotion: ['失落', '迷茫', '害怕一场空'],
    action: ['暂停灾难化推演', '补充信息后再决定'],
    forbidden: ['一切成空', '没有希望'],
    summary: '你缺的可能不是答案，而是一条还没拿到的事实。',
    micro: '写下你现在最缺的那一条信息，以及可以从哪里得到它。',
    positions: {
      起势: '你现在难受的，可能不是没有答案，而是关键信息一直是空的。',
      过程: '有一部分期待，目前还没有找到现实中的落点。',
      当下: '先暂停灾难化的推演，把缺的那条事实补上，再决定下一步。',
    },
  },
];

/* ---------- 三位置语料（文档 §5.6） ---------- */
export const POSITIONS = [
  { name: '起势', task: '说明用户为什么会在此刻提出问题' },
  { name: '过程', task: '说明问题如何被关系、环境或行为维持' },
  { name: '当下', task: '说明此刻值得优先处理的部分' },
];

/* ---------- 转折语料（文档 §5.8 示例表） ---------- */
export const TRANSITIONS = {
  'daan>liulian':     '表面稳定不等于问题已结束，可能仍有未说清的部分。',
  'liulian>suxi':     '反复之后可能出现变化，重点是先准备好如何回应。',
  'suxi>chikou':      '变化和急迫感可能放大误解，需要放慢沟通。',
  'chikou>xiaoji':    '摩擦并非只能升级，小范围协作可能打开出口。',
  'xiaoji>kongwang':  '有进展信号，但关键事实仍不足，不宜过度推演。',
  'kongwang>daan':    '从猜测回到事实和日常稳定，可能比继续追问更有效。',
};

export function transitionText(a, b) {
  if (a.id === b.id) return `同一种状态连续出现，值得留意它为什么一直没有变。`;
  return TRANSITIONS[`${a.id}>${b.id}`]
      || `从「${a.label}」到「${b.label}」，重点是这中间发生了什么，而不是哪一个更好。`;
}

/* ---------- 场景标签（文档 §5.7 六个场景包） ---------- */
export const TOPICS = [
  { id: 'relation', label: '关系与暧昧',  tint: '#ffe9e2', ink: '#ff6a3d' },
  { id: 'breakup',  label: '分手与复合',  tint: '#ffe8ec', ink: '#ff5a6e' },
  { id: 'study',    label: '学业与考试',  tint: '#e8effe', ink: '#2f6bff' },
  { id: 'work',     label: '工作与求职',  tint: '#dcf6ec', ink: '#17b57f' },
  { id: 'family',   label: '家庭与人际',  tint: '#f0eafe', ink: '#8153f0' },
  { id: 'self',     label: '自我与日常',  tint: '#fdf3d7', ink: '#e5a417' },
];

/* ---------- 示例心事（文档 §3.2 用户任务表） ---------- */
export const EXAMPLE_WORRIES = [
  { text: '我不知道该不该继续等他。',   topic: 'relation' },
  { text: '这次面试没消息，我是不是没戏了。', topic: 'work' },
  { text: '她最近很冷淡，是不是讨厌我了。',   topic: 'family' },
  { text: '我要不要去这个机会。',             topic: 'self' },
];

/* ============================================================
   确定性计算引擎（文档 §5.3）

   r1 = (n1 - 1) mod 6
   r2 = (r1 + n2 - 1) mod 6
   r3 = (r2 + n3 - 1) mod 6

   任何大模型均无权修改此结果（文档 §0.1）。
   ============================================================ */

/* 输入上界可配置。默认 6 = 文档 §5.2 的原始规定，V2 / V3 走这条。
   V4 放宽到 99，理由是分布偏差可接受：
     1–6   每宫各 1                 偏差 1.000
     1–9   前三宫 2 / 后三宫 1      偏差 2.000  ← §5.2 正是因为这个否掉 1–9
     1–99  前三宫 17 / 后三宫 16    偏差 1.063
   1–99 的 6% 偏差远小于人为选数的噪声（大家偏爱 7/8/13/66/88），
   而且这些幸运数经 mod 6 打散后反而摊平了宫位分布。
   若要绝对均匀可用 1–96（96 = 16×6）。
   顺推算法本身与上界无关，只有校验需要区分。 */
export const DEFAULT_MAX = 6;

export function isValidNumber(n, max = DEFAULT_MAX) {
  return Number.isInteger(n) && n >= 1 && n <= max;
}

export function calculate(n1, n2, n3, max = DEFAULT_MAX) {
  if (![n1, n2, n3].every(n => isValidNumber(n, max))) {
    throw new Error('INVALID_NUMBER_RANGE');
  }
  const r1 = (n1 - 1) % 6;
  const r2 = (r1 + n2 - 1) % 6;
  const r3 = (r2 + n3 - 1) % 6;
  return {
    method_version: METHOD_VERSION,
    corpus_version: CORPUS_VERSION,
    indices: [r1, r2, r3],
    palaces: [PALACES[r1], PALACES[r2], PALACES[r3]],
  };
}

/* ---------- 组合式解释生成（文档 §5.8） ----------
   不为 216 种组合手写断语：读取三个宫位的允许含义 +
   位置规则 + 相邻转折关系，组装结构化草稿。            */
export function buildReading(n1, n2, n3, max = DEFAULT_MAX) {
  const calc = calculate(n1, n2, n3, max);
  const [p1, p2, p3] = calc.palaces;
  return {
    method_version: calc.method_version,
    corpus_version: calc.corpus_version,
    numbers: [n1, n2, n3],
    result: calc.palaces.map(p => p.label),
    summary: p3.summary,
    positions: [
      { name: '起势', palace: p1, interpretation: p1.positions['起势'] },
      { name: '过程', palace: p2, interpretation: p2.positions['过程'] },
      { name: '当下', palace: p3, interpretation: p3.positions['当下'] },
    ],
    transitions: [transitionText(p1, p2), transitionText(p2, p3)],
    uncertainty: '这是一种自我反思线索，不是对未来的确定预测。同一个结果，换一件心事就需要不同的解释。',
    controllable: p3.action,
    micro_action: p3.micro,
    safety_flags: [],
  };
}

/* ---------- 黄金测试用例（文档 §5.4） ---------- */
export const GOLDEN_CASES = [
  { in: [1, 1, 1], out: ['大安', '大安', '大安'] },
  { in: [2, 5, 2], out: ['留连', '空亡', '大安'] },
  { in: [6, 6, 6], out: ['空亡', '小吉', '赤口'] },
  { in: [3, 3, 3], out: ['速喜', '小吉', '大安'] },
];

export function selfTest() {
  const fails = [];
  for (const c of GOLDEN_CASES) {
    const got = calculate(...c.in).palaces.map(p => p.label);
    if (got.join() !== c.out.join()) fails.push({ ...c, got });
  }
  // 穷举 216 种合法输入，全部必须得到三个有效宫位
  let count = 0;
  for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) for (let c = 1; c <= 6; c++) {
    const r = calculate(a, b, c);
    if (r.indices.every(i => i >= 0 && i <= 5) && r.palaces.every(Boolean)) count++;
  }
  // 越界输入必须被拒绝（默认上界 6）
  const rejects = [[7,1,1],[0,2,3],[2.5,3,4]];
  for (const r of rejects) {
    try { calculate(...r); fails.push({ in: r, out: '应拒绝', got: '未拒绝' }); }
    catch (e) { /* 预期 */ }
  }

  // V4 的 1–99 模式：穷举 99³ 太慢，抽查边界 + 校验分布偏差
  let wide = 0;
  for (const t of [[1,1,1],[99,99,99],[7,1,1],[50,73,88],[96,4,17]]) {
    try { const r = calculate(...t, 99);
      if (r.indices.every(i => i >= 0 && i <= 5)) wide++;
    } catch (e) { fails.push({ in: t, out: '1–99 应接受', got: e.message }); }
  }
  // 1–99 下仍须拒绝 0 / 100 / 小数
  for (const r of [[0,1,1],[100,1,1],[2.5,3,4]]) {
    try { calculate(...r, 99); fails.push({ in: r, out: '应拒绝', got: '未拒绝' }); }
    catch (e) { /* 预期 */ }
  }
  // 分布偏差：1–99 下最常/最少宫位之比应 ≤ 1.07
  const hist = [0,0,0,0,0,0];
  for (let n = 1; n <= 99; n++) hist[(n - 1) % 6]++;
  const skew = Math.max(...hist) / Math.min(...hist);
  if (skew > 1.07) fails.push({ in: '1–99 分布', out: '≤1.07', got: skew.toFixed(3) });

  return { pass: fails.length === 0 && count === 216 && wide === 5,
           exhaustive: count, wide, skew: +skew.toFixed(3), fails };
}
