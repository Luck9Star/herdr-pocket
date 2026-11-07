import { UnicodeGraphemesAddon } from '@xterm/addon-unicode-graphemes';

// Register grapheme-aware Unicode 15 rules before the first terminal write.
// xterm 6 exposes its Unicode provider through a proposed API.
export function createUnicodeTerminal(Terminal, options) {
  const terminal = new Terminal({...options, allowProposedApi:true});
  terminal.loadAddon(new UnicodeGraphemesAddon());
  return terminal;
}
