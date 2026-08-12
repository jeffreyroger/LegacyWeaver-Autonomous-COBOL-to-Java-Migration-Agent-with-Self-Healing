// Minimal Java syntax highlighter for the synthesized method-body fragments
// the backend returns (weaver.agent's candidate/committed bodies) -- display
// only, no parsing decisions feed back into anything that affects correctness.

const JAVA_KEYWORDS = new Set([
  'public', 'private', 'protected', 'static', 'final', 'abstract', 'class', 'interface', 'enum',
  'extends', 'implements', 'new', 'return', 'void', 'if', 'else', 'for', 'while', 'do', 'switch',
  'case', 'default', 'break', 'continue', 'try', 'catch', 'finally', 'throw', 'throws', 'import',
  'package', 'this', 'super', 'null', 'true', 'false', 'instanceof', 'synchronized', 'volatile',
  'transient', 'const', 'goto', 'assert', 'var',
])

const JAVA_PRIMITIVES = new Set(['int', 'long', 'short', 'byte', 'char', 'boolean', 'float', 'double'])

// Token: {text, cls} -- cls is one of t-kw/t-type/t-str/t-num/t-cmt/t-method/null.
export function tokenizeJavaLine(text) {
  const out = []
  const re = /("(?:[^"\\]|\\.)*"|\/\/.*$|\b0[xX][0-9a-fA-F]+\b|\b\d+(?:\.\d+)?[fFdDlL]?\b|[A-Za-z_$][A-Za-z0-9_$]*|\s+|.)/g
  let m
  while ((m = re.exec(text)) !== null) {
    const w = m[0]
    if (/^\s+$/.test(w)) { out.push({ text: w, cls: null }); continue }
    if (w.startsWith('"')) { out.push({ text: w, cls: 't-str' }); continue }
    if (w.startsWith('//')) { out.push({ text: w, cls: 't-cmt' }); continue }
    if (/^(0[xX][0-9a-fA-F]+|\d+(\.\d+)?[fFdDlL]?)$/.test(w)) { out.push({ text: w, cls: 't-num' }); continue }
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(w)) {
      if (JAVA_KEYWORDS.has(w) || JAVA_PRIMITIVES.has(w)) { out.push({ text: w, cls: 't-kw' }); continue }
      // A capitalized identifier is a class/type reference (BigDecimal, RoundingMode, ...).
      if (/^[A-Z]/.test(w)) { out.push({ text: w, cls: 't-type' }); continue }
      // An identifier immediately followed by '(' (skipping whitespace) is a method/call name.
      const rest = text.slice(re.lastIndex)
      if (/^\s*\(/.test(rest)) { out.push({ text: w, cls: 't-method' }); continue }
      out.push({ text: w, cls: null })
      continue
    }
    out.push({ text: w, cls: null })
  }
  return out
}
