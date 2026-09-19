// Test oracle: evaluate the input with the existing official Spine runtime.
import fs from 'node:fs';
import { SkeletonJson, Skeleton, RegionAttachment, MixBlend, MixDirection, Physics }
  from '../app/frontend/node_modules/@esotericsoftware/spine-core/dist/index.js';

const data = new SkeletonJson({
  newRegionAttachment: (_skin, name, path) => new RegionAttachment(name, path),
}).readSkeletonData(JSON.parse(fs.readFileSync(process.argv[2], 'utf8')));
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const results = cases.map(c => {
  const skeleton = new Skeleton(data);
  data.findAnimation(c.clip).apply(skeleton, 0, c.time, false, [], 1, MixBlend.replace, MixDirection.mixIn);
  skeleton.updateWorldTransform(Physics.none);
  return Object.fromEntries(skeleton.bones.map(b => [b.data.name, [b.a, -b.c, -b.b, b.d, b.worldX, -b.worldY]]));
});
process.stdout.write(JSON.stringify(results));
