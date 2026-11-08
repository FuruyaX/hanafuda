// Pyodide を読み込み、Python のゲーム本体（main.py）を起動するだけの最小ローダー。
import { loadPyodide } from './pyodide/pyodide.mjs';
import './net.js';

const status = document.getElementById('status');
let pyodide = null;

// ---- PWA: インストールボタン用 ----
let installPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  installPrompt = e;
  pyodide?.runPython('import main\nif main.app: main.app.render()');
});
window.canInstall = () => installPrompt !== null;
window.isIOS = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
window.installApp = async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
};

// ---- オフライン用 Service Worker（HTTPS または localhost でのみ有効） ----
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('./sw.js').catch((e) => console.warn('SW:', e));
}

if (location.search.includes('nettest')) {
  // 通信層の自己診断: 同じ画面の中でホストとゲストをつないで確かめる
  window.net
    .selfTest()
    .then((r) => (document.title = status.textContent = 'NETTEST OK ' + JSON.stringify(r)))
    .catch((e) => (document.title = status.textContent = 'NETTEST NG ' + e));
  throw new Error('nettest');
}

try {
  status.textContent = 'Python を起動中…';
  pyodide = await loadPyodide({ indexURL: new URL('./pyodide/', location.href).href });

  status.textContent = 'ゲームを読み込み中…';
  const files = await (await fetch('./app-files.json')).json();
  for (const path of files) {
    const dir = '/app/' + path.split('/').slice(0, -1).join('/');
    pyodide.FS.mkdirTree(dir);
    pyodide.FS.writeFile('/app/' + path, await (await fetch('./' + path)).text());
  }
  pyodide.runPython("import sys; sys.path.insert(0, '/app')\nimport main\nmain.start()");
} catch (e) {
  console.error(e);
  status.textContent = '起動に失敗しました: ' + e;
}
