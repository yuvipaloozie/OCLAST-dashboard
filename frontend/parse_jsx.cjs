const fs = require('fs');
const acorn = require('acorn');
const jsx = require('acorn-jsx');

const Parser = acorn.Parser.extend(jsx());
const code = fs.readFileSync('d:/Personal Projects/OCLAST-dashboard/frontend/src/App.jsx', 'utf8');

try {
  Parser.parse(code, { sourceType: 'module', ecmaVersion: 2020 });
  console.log("No syntax errors found!");
} catch (e) {
  console.error("Syntax Error:", e.message);
  console.error("At line:", e.loc.line, "column:", e.loc.column);
  
  // Let's print the surrounding code
  const lines = code.split('\n');
  const start = Math.max(0, e.loc.line - 10);
  const end = Math.min(lines.length, e.loc.line + 10);
  for (let i = start; i < end; i++) {
    console.log(`${i + 1}: ${lines[i]}`);
  }
}
