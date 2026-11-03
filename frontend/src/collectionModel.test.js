import test from 'node:test';
import assert from 'node:assert/strict';
import {collectionSelection,formatMeasurement,sortImageRows} from './collectionModel.js';

test('new completed images join all-object export scope unless explicitly excluded',()=>{
  const excluded=new Set(['b']);
  assert.deepEqual(collectionSelection(['a','b','c'],excluded),['a','c']);
  assert.deepEqual(collectionSelection(['a','b','c','new-image'],excluded),['a','c','new-image']);
});

test('filtering and sorting the view does not silently narrow CSV selection',()=>{
  const projects=[{id:'a',name:'field_10.tif',source_path:'batch/field_10.tif',status:'complete',count:0},{id:'b',name:'field_2.tif',status:'complete',count:12},{id:'c',name:'field_1.tif',status:'ready',count:0}];
  const summary=new Map([['a',{median_area:null}],['b',{median_area:200}]]);
  assert.deepEqual(sortImageRows(projects,summary,'field_2','name').map(p=>p.id),['b']);
  assert.deepEqual(collectionSelection(['a','b'],new Set()),['a','b']);
  assert.deepEqual(sortImageRows(projects,summary,'','name').map(p=>p.id),['c','b','a']);
  assert.deepEqual(sortImageRows(projects,summary,'','area').map(p=>p.id),['b','c','a']);
});

test('missing morphology stays distinct from a legitimate measured zero',()=>{
  assert.equal(formatMeasurement(null),'—');
  assert.equal(formatMeasurement(undefined),'—');
  assert.equal(formatMeasurement(NaN),'—');
  assert.equal(formatMeasurement(0,3),'0.000');
  assert.equal(formatMeasurement(.9134,3),'0.913');
});
