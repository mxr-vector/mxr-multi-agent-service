import {Config} from '@remotion/cli/config';
import {existsSync} from 'node:fs';

// 中国网络下默认下载 Chrome Headless Shell 会卡在 storage.googleapis.com（113MB）。
// 优先用系统已装的 Chrome（和 paper-cutout-remotion / demo-wx-article 系列一致），跳过下载。
const browserCandidates = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
];
for (const p of browserCandidates) {
  if (existsSync(p)) {
    Config.setBrowserExecutable(p);
    break;
  }
}

// 并发度 1：单 worker 避免 Windows temp 目录竞争导致音频混合（audio-mixing）失败。
// 绝对不要同时跑多个 remotion render。
Config.setConcurrency(1);

Config.setPublicDir('./public');
Config.setOverwriteOutput(true);
Config.setVideoImageFormat('jpeg');
