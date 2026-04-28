import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const projectRoot = process.cwd();
const vendorDir = resolve(projectRoot, 'frontend', 'src', 'static', 'vendor', 'twilio', 'voice-sdk');

const files = [
  {
    source: resolve(projectRoot, 'node_modules', '@twilio', 'voice-sdk', 'dist', 'twilio.min.js'),
    target: resolve(vendorDir, 'twilio.min.js'),
  },
  {
    source: resolve(projectRoot, 'node_modules', '@twilio', 'voice-sdk', 'LICENSE.md'),
    target: resolve(vendorDir, 'LICENSE.md'),
  },
];

for (const file of files) {
  mkdirSync(dirname(file.target), { recursive: true });
  copyFileSync(file.source, file.target);
  console.log(`synced ${file.target}`);
}
