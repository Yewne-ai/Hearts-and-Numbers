/* ============================================================
   于你 Yewne — 六宫记号系统 v1
   V3 专有的视觉层。内容与算法仍来自 ../v2-product/corpus.js。

   设计规则：
   1. 同源构成 —— 全部由「一条基准横线 + 圆的一种状态」生成。
      横线 = 你正在经历的这件事；圆的形态 = 此刻的状态。
   2. 当字排，不当图标用 —— 尺寸、笔重对齐正文，可以行内混排。
      汉字密而重，所以笔画比 Co-Star 的发丝级行星符号更实一档。
   3. 不做吉凶编码 —— 没有叉号、没有上下箭头、没有红绿语义。
      「赤口」用错位而不是叉号，因为叉在界面里读作「错误」。
   4. 不借爻卦 —— 文档 §5.1 承诺不混入六爻或其他体系，
      阴阳爻的断线实线会把易经系统偷偷带进来。

   唯一的例外：「空亡」的基准线在圆内断开。
   信息不足 / 悬置，线就是断的。这是记号里唯一携带语义的破例。
   ============================================================ */

/* 六宫在「纸」上的用色。主界面全墨，颜色只出现在 Aftercare
   与心事地图的宣纸卡上（V3 色彩策略）。
   刻意保持 V2 的反吉凶映射：绿给赤口（摩擦），红给小吉（小进展）。 */
export const PAPER_INK = {
  daan:     '#3F5F87',   // 蓝
  liulian:  '#64518A',   // 紫
  suxi:     '#A85F38',   // 陶橙
  chikou:   '#46745A',   // 绿  ← 摩擦
  xiaoji:   '#9E4650',   // 红  ← 小进展
  kongwang: '#8A6E2C',   // 赭
};

const W = 40, MID = 20, Y = 8, R = 4.2;

/* 每个记号返回 viewBox="0 0 40 16" 内的路径组。
   currentColor 驱动，行内排版时自动继承文字颜色。 */
const MARKS = {
  // 大安 —— 实心，落定
  daan: `<line x1="0" y1="${Y}" x2="${W}" y2="${Y}"/>
         <circle cx="${MID}" cy="${Y}" r="${R}" fill="currentColor" stroke="none"/>`,

  // 留连 —— 绕了一圈又回到原处
  // 初版用「未闭合的环」，弧口在正文尺寸下与「空亡」的空心圆读不出差别。
  // 改为同心双环：语义仍是回环，且与单环拉开明确距离。
  liulian: `<line x1="0" y1="${Y}" x2="${W}" y2="${Y}"/>
            <circle cx="${MID}" cy="${Y}" r="${R}" fill="none"/>
            <circle cx="${MID}" cy="${Y}" r="1.7" fill="none"/>`,

  // 速喜 —— 有方向，往前
  suxi: `<line x1="0" y1="${Y}" x2="${W}" y2="${Y}"/>
         <path d="M16.6 3.7 24.4 ${Y} 16.6 12.3Z" fill="currentColor" stroke="none"/>`,

  // 赤口 —— 两笔错开，不在一条线上
  chikou: `<line x1="0" y1="${Y}" x2="${W}" y2="${Y}"/>
           <line x1="17.2" y1="2.4" x2="17.2" y2="${Y}"/>
           <line x1="22.8" y1="${Y}" x2="22.8" y2="13.6"/>`,

  // 小吉 —— 开了一半
  xiaoji: `<line x1="0" y1="${Y}" x2="${W}" y2="${Y}"/>
           <path d="M${MID} ${Y - R}a${R} ${R} 0 0 1 0 ${R * 2}Z" fill="currentColor" stroke="none"/>
           <circle cx="${MID}" cy="${Y}" r="${R}" fill="none"/>`,

  // 空亡 —— 空的，且基准线在圆两侧明确断开
  // 断口必须留出可见间隙，紧贴圆缘等于没断。
  kongwang: `<line x1="0" y1="${Y}" x2="${MID - R - 3}" y2="${Y}"/>
             <line x1="${MID + R + 3}" y1="${Y}" x2="${W}" y2="${Y}"/>
             <circle cx="${MID}" cy="${Y}" r="${R}" fill="none"/>`,
};

/**
 * 单个宫位记号。
 * @param id     宫位 id
 * @param scale  相对基准尺寸的倍数（正文行内用 1，标题用 1.4）
 * @param color  可选。不传则继承 currentColor（主界面全墨走这条）
 */
export function glyph(id, scale = 1, color = null) {
  const w = W * scale, h = 16 * scale;
  return `<svg class="gl" width="${w}" height="${h}" viewBox="0 0 ${W} 16"
            fill="none" stroke="${color || 'currentColor'}" stroke-width="1.5"
            stroke-linecap="round" aria-hidden="true"
            ${color ? `style="color:${color}"` : ''}>${MARKS[id]}</svg>`;
}

/**
 * 会话签名 —— 三宫连成一行记号。
 * 三个 glyph 的基准线首尾相接，读起来是一条连续的记谱。
 * @param onPaper  true 时上六宫色（纸卡），false 时全墨（主界面）
 */
export function signature(palaces, scale = 1, onPaper = false) {
  return `<span class="sig">${
    palaces.map(p => glyph(p.id, scale, onPaper ? PAPER_INK[p.id] : null)).join('')
  }</span>`;
}
