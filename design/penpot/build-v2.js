// Herdr Pocket - v2 High-Fidelity & Engineering Design Builder
// Theme: Option A (Tech Indigo & Slate)
// Target File: b55064db-d93d-80f9-8008-ddd22e6d398f, Page: 7a22df08-251d-8016-8008-de03541c11da

if (penpot.currentFile?.id !== 'b55064db-d93d-80f9-8008-ddd22e6d398f') {
  throw new Error('Wrong Penpot file; refusing writes');
}

await penpot.openPage('7a22df08-251d-8016-8008-de03541c11da');

if (!storage.hp2) storage.hp2 = {};
const hp = storage.hp2;

hp.sanitizeName = function(name) {
  if (!name) return 'shape';
  const clean = String(name).replace(/[\/]+/g, '-').trim();
  return clean.length > 0 ? clean : 'shape';
};

hp.colors = {
  canvas: '#F8FAFC',
  card: '#FFFFFF',
  cardSubtle: '#F1F5F9',
  border: '#E2E8F0',
  borderStrong: '#CBD5E1',
  textPrimary: '#0F172A',
  textSecondary: '#475569',
  textMuted: '#94A3B8',
  textInverse: '#FFFFFF',
  
  // Tech Indigo 600 (Replaces old teal green to avoid status collision)
  brand: '#4F46E5',
  brandHover: '#4338CA',
  brandSoft: '#EEF2FF',
  brandBorder: '#C7D2FE',
  
  // Status colors (Cleanly separated: Emerald 100% reserved for Online/Passed)
  success: '#10B981',
  successSoft: '#ECFDF5',
  successBorder: '#A7F3D0',
  warning: '#F59E0B',
  warningSoft: '#FEF3C7',
  warningBorder: '#FDE68A',
  danger: '#F43F5E',
  dangerSoft: '#FFF1F2',
  dangerBorder: '#FECDD3',
  info: '#0284C7',
  infoSoft: '#E0F2FE',
  infoBorder: '#BAE6FD',
  
  // Terminal palette (Obsidian Dark)
  termBg: '#0B0F17',
  termSurface: '#111827',
  termBorder: '#1F2937',
  termText: '#E6EDF3',
  termMuted: '#7D8B99',
  termPrompt: '#60A5FA',
  termSuccess: '#34D399',
  termWarning: '#FBBF24',
  termDanger: '#FB7185',
  termCursor: '#818CF8',
  termKeyBg: '#1F2937',
  termKeyBorder: '#374151'
};

hp.fontUI = penpot.fonts.findByName('Inter') || penpot.fonts.findByName('Noto Sans SC');
hp.fontMono = penpot.fonts.findByName('JetBrains Mono') || penpot.fonts.findByName('Roboto Mono') || hp.fontUI;

hp.createBoard = function(id, title, x, y, w = 390, h = 844) {
  const b = penpot.createBoard();
  b.name = id + ' · ' + title;
  b.resize(w, h);
  b.x = x;
  b.y = y;
  b.borderRadius = 20;
  b.fills = [{ fillColor: hp.colors.canvas, fillOpacity: 1 }];
  b.strokes = [{ strokeColor: hp.colors.border, strokeWidth: 1, strokeStyle: 'solid', strokeAlignment: 'inner' }];
  b.shadows = [{
    style: 'drop-shadow',
    offsetX: 0,
    offsetY: 8,
    blur: 24,
    color: { color: '#0F172A', opacity: 0.06 }
  }];
  b.clipContent = true;
  b.showInViewMode = true;
  b.setPluginData('herdr-pocket', JSON.stringify({ screen: id, version: 'v2-tech-indigo', type: 'high-fi-scheme' }));
  return b;
};

hp.rect = function(parent, x, y, w, h, opts = {}) {
  const r = penpot.createRectangle();
  r.resize(w, h);
  r.name = hp.sanitizeName(opts.name || 'rect');
  r.borderRadius = opts.radius !== undefined ? opts.radius : 8;
  const fillCol = opts.fill ? (hp.colors[opts.fill] || opts.fill) : 'transparent';
  if (fillCol !== 'transparent') {
    r.fills = [{ fillColor: fillCol, fillOpacity: opts.fillOpacity !== undefined ? opts.fillOpacity : 1 }];
  } else {
    r.fills = [];
  }
  if (opts.stroke) {
    r.strokes = [{
      strokeColor: hp.colors[opts.stroke] || opts.stroke,
      strokeWidth: opts.strokeWidth || 1,
      strokeStyle: 'solid',
      strokeAlignment: opts.strokeAlignment || 'inner'
    }];
  }
  if (opts.shadow) r.shadows = [opts.shadow];
  if (parent) parent.appendChild(r);
  r.x = (parent ? parent.x : 0) + x;
  r.y = (parent ? parent.y : 0) + y;
  return r;
};

hp.text = function(parent, x, y, w, h, content, opts = {}) {
  const safeContent = (content !== undefined && content !== null && String(content).length > 0) ? String(content) : ' ';
  const t = penpot.createText(safeContent);
  t.resize(w, h);
  t.name = hp.sanitizeName(opts.name || safeContent.split('\n')[0] || 'text').slice(0, 40);
  t.growType = opts.growType || 'fixed';
  const font = opts.mono ? hp.fontMono : hp.fontUI;
  if (font) font.applyToText(t);
  t.fontSize = String(opts.size || 14);
  t.fontWeight = String(opts.weight || 400);
  t.lineHeight = String(opts.lineHeight || 1.45);
  if (opts.align) t.align = opts.align;
  const colorHex = hp.colors[opts.color] || opts.color || hp.colors.textPrimary;
  t.fills = [{ fillColor: colorHex, fillOpacity: opts.opacity !== undefined ? opts.opacity : 1 }];
  if (parent) parent.appendChild(t);
  t.x = (parent ? parent.x : 0) + x;
  t.y = (parent ? parent.y : 0) + y;
  return t;
};

hp.badge = function(parent, x, y, label, variant = 'brand', opts = {}) {
  const variants = {
    brand: { bg: hp.colors.brandSoft, text: hp.colors.brand, border: hp.colors.brandBorder },
    success: { bg: hp.colors.successSoft, text: hp.colors.success, border: hp.colors.successBorder },
    warning: { bg: hp.colors.warningSoft, text: hp.colors.warning, border: hp.colors.warningBorder },
    danger: { bg: hp.colors.dangerSoft, text: hp.colors.danger, border: hp.colors.dangerBorder },
    info: { bg: hp.colors.infoSoft, text: hp.colors.info, border: hp.colors.infoBorder },
    neutral: { bg: hp.colors.cardSubtle, text: hp.colors.textSecondary, border: hp.colors.border },
    dark: { bg: hp.colors.termSurface, text: hp.colors.termText, border: hp.colors.termBorder }
  };
  const v = variants[variant] || variants.brand;
  const pad = opts.padding || 8;
  const w = opts.width || (label.length * 8 + pad * 2 + 10);
  const h = opts.height || 24;
  const bg = hp.rect(parent, x, y, w, h, {
    name: 'badge-' + variant,
    fill: v.bg,
    radius: 999,
    stroke: v.border,
    strokeWidth: 1
  });
  const t = hp.text(parent, x + pad, y + 4, w - pad * 2, h - 8, label, {
    name: 'badge-text',
    size: 11,
    weight: 600,
    color: v.text,
    align: 'center',
    mono: opts.mono
  });
  return { bg, text: t };
};

hp.button = function(parent, x, y, w, h, label, variant = 'primary', opts = {}) {
  const isPrimary = variant === 'primary';
  const isDanger = variant === 'danger';
  const isGhost = variant === 'ghost';
  let bgCol = isPrimary ? hp.colors.brand : isDanger ? hp.colors.danger : isGhost ? 'transparent' : hp.colors.card;
  let textCol = (isPrimary || isDanger) ? hp.colors.textInverse : hp.colors.textPrimary;
  let strokeCol = (isPrimary || isDanger || isGhost) ? null : hp.colors.border;
  const btn = hp.rect(parent, x, y, w, h, {
    name: 'button-' + variant,
    fill: bgCol,
    radius: opts.radius || 10,
    stroke: strokeCol,
    strokeWidth: 1,
    shadow: isPrimary ? {
      style: 'drop-shadow',
      offsetX: 0,
      offsetY: 2,
      blur: 8,
      color: { color: hp.colors.brand, opacity: 0.25 }
    } : null
  });
  const txt = hp.text(parent, x + 8, y + Math.floor((h - 18) / 2), w - 16, 20, label, {
    name: 'button-label',
    size: opts.size || 13,
    weight: 600,
    color: textCol,
    align: 'center'
  });
  return { bg: btn, text: txt };
};

hp.statusBar = function(parent, dark = false) {
  const col = dark ? hp.colors.termText : hp.colors.textPrimary;
  hp.text(parent, 24, 13, 54, 20, '16:40', { size: 14, weight: 600, color: col });
  hp.rect(parent, (parent.width - 96) / 2, 9, 96, 24, {
    fill: dark ? '#000000' : '#0F172A',
    radius: 999
  });
  hp.text(parent, parent.width - 76, 14, 52, 20, '5G  100%', { size: 11, weight: 600, color: col, align: 'right' });
};
