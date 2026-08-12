// Minimal COBOL line tokenizer for syntax highlighting, ported from the
// original static mockup (frontend.html) — pure display logic, no parsing
// decisions that affect correctness (that all lives in zuse/cobol/).

const COBOL_VERBS = ['COMPUTE', 'MOVE', 'PERFORM', 'IF', 'ELSE', 'DISPLAY', 'ACCEPT', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'READ', 'WRITE', 'OPEN', 'CLOSE', 'STOP', 'EVALUATE', 'SET', 'CALL']
const COBOL_KW = ['ROUNDED', 'ON', 'SIZE', 'ERROR', 'TO', 'FROM', 'BY', 'GIVING', 'THRU', 'UNTIL', 'VARYING', 'END-COMPUTE', 'END-IF', 'END-PERFORM', 'END-EVALUATE', 'PIC', 'COMP-3', 'COMP', 'VALUE', 'RUN']
const COBOL_FIG = ['ZEROS', 'ZERO', 'ZEROES', 'SPACES', 'SPACE', 'HIGH-VALUES', 'LOW-VALUES']

// Returns an array of {text, cls} tokens for one source line (cls === null for plain text).
export function tokenizeCobolLine(text) {
  if (/^\s*\*>/.test(text)) return [{ text, cls: 't-cmt' }]
  if (/\b(DIVISION|SECTION)\s*\.\s*$/.test(text)) return [{ text, cls: 't-div' }]
  if (/^\s*PROGRAM-ID\./.test(text)) {
    const m = text.match(/^(\s*)(PROGRAM-ID\.)(.*)$/)
    if (m) return [{ text: m[1], cls: null }, { text: m[2], cls: 't-div' }, { text: m[3], cls: 't-para' }]
  }
  if (/^\s+[A-Z0-9][A-Z0-9-]*\.\s*$/.test(text) && !/\b(DIVISION|SECTION)\b/.test(text) && !/^\s+END-/.test(text)) {
    return [{ text, cls: 't-para' }]
  }
  const out = []
  const re = /([A-Z0-9][A-Z0-9()\-]*|\S|\s+)/g
  let m
  let afterPic = false
  while ((m = re.exec(text)) !== null) {
    const w = m[0]
    if (/^\s+$/.test(w)) { out.push({ text: w, cls: null }); continue }
    const word = w.toUpperCase()
    if (afterPic && /^[SX9VA()0-9]+$/.test(word)) { out.push({ text: w, cls: 't-pic' }); afterPic = false; continue }
    afterPic = false
    if (word === 'PIC' || word === 'PICTURE') { out.push({ text: w, cls: 't-kw' }); afterPic = true }
    else if (/^0[1-9]$|^[1-4][0-9]$|^77$|^88$/.test(word) && /^\s*$/.test(text.slice(0, m.index))) out.push({ text: w, cls: 't-lvl' })
    else if (COBOL_VERBS.includes(word)) out.push({ text: w, cls: 't-verb' })
    else if (COBOL_KW.includes(word)) out.push({ text: w, cls: 't-kw' })
    else if (COBOL_FIG.includes(word) || /^[0-9]+(\.[0-9]+)?$/.test(word)) out.push({ text: w, cls: 't-num' })
    else if (/^WS-|^FD-|^TL-|^RL-/.test(word)) out.push({ text: w, cls: 't-id' })
    else out.push({ text: w, cls: null })
  }
  return out
}

// Splits COBOL source text into [{seq, text}] rows the way the original
// six-digit-sequence-area mockup rendered them -- falls back to a running
// counter when the source has no sequence-area numbering.
export function toSourceRows(text) {
  return text.split('\n').map((line, i) => {
    const m = line.match(/^(\d{6})(.*)$/)
    return m ? { seq: m[1], text: m[2] } : { seq: String(i + 1).padStart(6, '0'), text: line }
  })
}
