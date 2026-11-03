import test from 'node:test';
import assert from 'node:assert/strict';
import {duration,importFiles} from './workflow.js';

test('durations preserve subsecond results and normalize minute carry',()=>{
  assert.equal(duration(.34),'<1s');assert.equal(duration(119.7),'2m 0s');assert.equal(duration(null),'—');assert.equal(duration(0),'0s');
});
test('mixed folder imports preserve order and reject unsupported or oversized files individually',()=>{
  const good={name:'sample.TIFF',size:180000000,webkitRelativePath:'series/sample.TIFF'};
  const other={name:'field.png',size:100};
  const result=importFiles([good,{name:'notes.txt',size:4},{name:'huge.tif',size:600*1024**2},other]);
  assert.deepEqual(result.accepted,[good,other]);assert.equal(result.issues.length,2);
});
