import test from 'node:test';
import assert from 'node:assert/strict';
import {axisFor,describe,inRange,presetIds} from './objectInsights.js';

test('descriptive statistics use interpolated percentiles and handle empty selections',()=>{
  const cells=[100,200,300,400].map((area,i)=>({area,circularity:[.1,.4,.7,1][i]}));
  const s=describe(cells);
  assert.deepEqual([s.count,s.medianArea,s.q1,s.q3,s.p10,s.p90],[4,250,175,325,130,370]);
  assert.ok(Math.abs(s.medianCircularity-.55)<1e-10);
  assert.equal(describe([]).medianArea,null);
  assert.equal(describe([{area:20,circularity:.9}]).p90,20);
});

test('range selection includes boundary values without duplicating or inventing IDs',()=>{
  const cells=[{id:7,area:100,circularity:.5},{id:8,area:200,circularity:.8},{id:9,area:300,circularity:1}];
  assert.deepEqual(inRange(cells,'area','circularity',{x0:100,x1:200,y0:.5,y1:.8}),[7,8]);
  assert.deepEqual(inRange(cells,'area','circularity',{x0:1000,x1:2000,y0:0,y1:1}),[]);
});

test('presets rank values deterministically and find actual image-edge masks',()=>{
  const cells=Array.from({length:20},(_,i)=>({id:i+1,area:100+i,circularity:1-i/100,bbox:[1,1,9,9]}));
  cells[3].bbox=[0,1,9,9];cells[9].bbox=[1,1,10,9];
  assert.deepEqual(presetIds(cells,'largest',10,10),[20,19]);
  assert.deepEqual(presetIds(cells,'least-round',10,10),[20,19]);
  assert.deepEqual(presetIds(cells,'edge',10,10),[4,10]);
  assert.equal(presetIds(cells,'all',10,10),null);
});

test('linear and log axes preserve raw values and include every object',()=>{
  const cells=[100,1000,10000].map(area=>({area}));
  for(const log of [false,true]){
    const axis=axisFor(cells,'area',log);
    for(const c of cells){assert.ok(axis.position(c.area)>0&&axis.position(c.area)<1);assert.ok(Math.abs(axis.value(axis.position(c.area))-c.area)<1e-7);}
  }
  const log=axisFor(cells,'area',true);
  assert.ok(Math.abs(log.position(1000)-.5)<1e-9);
});

test('constant bounded measurements and empty plots have valid physical ranges',()=>{
  for(const value of [0,.8,1]){
    const axis=axisFor([{circularity:value}],'circularity');
    assert.ok(axis.min>=0&&axis.max<=1&&axis.max>axis.min);
    assert.ok(Number.isFinite(axis.position(value)));
  }
  assert.ok(Number.isFinite(axisFor([],'area').mid));
});
