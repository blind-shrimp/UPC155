// Decompress DSH session logs (concatenated zstd JSONL frames) for the AI-use report.
// Usage: node decompress_dsh_sessions.js <sessionsRoot> <outputDir>
//   sessionsRoot: e.g. C:/Users/<user>/.dsh/sessions
//   outputDir   : where *.jsonl plain-text copies are written
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

function frameStarts(buf) {
  const out = [];
  for (let i = 0; i + 3 < buf.length; i++) {
    if (buf[i] === 0x28 && buf[i + 1] === 0xb5 && buf[i + 2] === 0x2f && buf[i + 3] === 0xfd) out.push(i);
  }
  return out;
}

function decode(buf) {
  try { return zlib.zstdDecompressSync(buf).toString('utf8'); } catch (e) { return null; }
}

function decompressAll(buf) {
  const starts = frameStarts(buf);
  let text = '';
  let i = 0;
  while (i < starts.length) {
    const start = starts[i];
    let end = i + 1 < starts.length ? starts[i + 1] : buf.length;
    let decoded = decode(buf.subarray(start, end));
    let j = i + 1;
    while (decoded === null && j < starts.length) {
      end = j + 1 < starts.length ? starts[j + 1] : buf.length;
      decoded = decode(buf.subarray(start, end));
      j += 1;
    }
    if (decoded !== null) text += decoded;
    i = j;
  }
  return text;
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith('.jsonl.zstd')) out.push(p);
  }
  return out;
}

const root = process.argv[2];
const outDir = process.argv[3];
if (!root || !outDir) { console.error('usage: node decompress_dsh_sessions.js <sessionsRoot> <outputDir>'); process.exit(2); }
fs.mkdirSync(outDir, { recursive: true });
let n = 0;
for (const file of walk(root)) {
  const id = path.basename(path.dirname(file)) || path.basename(file).replace('.jsonl.zstd', '');
  const text = decompressAll(fs.readFileSync(file));
  if (!text) continue;
  // keep only sessions from the UPC workspaces
  if (!/ChatGPT-upc|Files-upc/i.test(text) && !/ChatGPT-upc|Files-upc/i.test(dirOf(file))) continue;
  fs.writeFileSync(path.join(outDir, id.replace(/[^\w.-]/g, '_') + '.jsonl'), text, 'utf8');
  n += 1;
}
console.log('decompressed sessions:', n, '->', outDir);

function dirOf(p) { return path.dirname(p); }
