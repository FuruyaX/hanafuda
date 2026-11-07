# 花札こいこい（Python + Pyodide / PWA）

花札の「こいこい」（2 人）と「花合わせ」（3 人）で CPU と対戦するゲームです。ゲームロジックも画面描画も Python で書かれ、
ブラウザ内の Python（[Pyodide](https://pyodide.org/)）で動きます。
スマホでは「ホーム画面に追加」するとアプリのように起動し、オフラインで遊べます（PWA）。

仕様・ルール・開発方針は [CLAUDE.md](CLAUDE.md) を参照。

## セットアップ（Docker）

ホストに Python 等はインストールしません。Pyodide 本体とビルド結果は Docker ボリュームに置かれ、
Google Drive の同期フォルダには入りません。

| 環境 | コマンド |
| --- | --- |
| Windows（ダブルクリック） | `setup.cmd`（必要なら準備して起動） |
| Windows（PowerShell） | `powershell -ExecutionPolicy Bypass -File .\setup.ps1 <command>` |
| macOS / Linux | `./setup.sh <command>` |

| command | 内容 |
| --- | --- |
| `setup`（省略時） | イメージ作成 → Pyodide 取得 → テスト |
| `start` | 開発サーバー起動 → http://localhost:8000 を開く（保存すると自動で再ビルド） |
| `stop` / `logs` / `shell` | 停止 / ログ / コンテナ内シェル |
| `test` | テスト（pytest） |
| `export` | 公開用の静的サイトを `dist/` に出力 |
| `update` | （要ネット）ベースイメージを最新化 |
| `clean` | コンテナ・ボリューム・イメージを削除 |

一度オンラインで `setup` を済ませれば、`update` 以外はオフラインで動きます。

## スマホで遊ぶ

- **同じ Wi-Fi で試す**: `start` で表示される `http://<PCのIP>:8000` をスマホで開く。
  遊べますが、http のためインストールとオフライン動作はできません。
  （Windows のファイアウォールで 8000 番の許可が必要な場合があります）
- **アプリとしてインストール**: `export` した `dist/` を HTTPS の静的ホスティング
  （GitHub Pages など）に置き、スマホで開いて
  - Android（Chrome）: タイトル画面の「アプリとしてインストール」またはメニュー →「ホーム画面に追加」
  - iPhone（Safari）: 共有ボタン →「ホーム画面に追加」

  一度開けば全ファイルがキャッシュされ、以降はオフラインで起動できます。

## 遊び方

1. タイトルでモード（こいこい / 花合わせ）と月数（3 / 6 / 12）を選んで「対戦開始」
2. 手札をタップ → 取れる場札が光る → 同じ札をもう一度タップ（または光った場札をタップ）で出す
3. 山札が自動でめくられる。取る札が 2 枚あるときは光った札から選ぶ
4. 役ができたら「勝負」か「こいこい」
5. 「デモ」で CPU 同士の自動対戦を見られます（URL に `?demo` / `?demo&hanaawase` を付けても開始）
6. 花合わせはこいこいなし。全員の手札がなくなったら、札の点数・出来役・手役で精算します

## 構成

```
hanafuda/   ゲームロジック（cards / yaku / game / ai）— CPython でテスト、ブラウザでも同じコード
web/        main.py（画面）、index.html、style.css、loader.js（Pyodide 起動）、sw.js、manifest
scripts/    build.py（静的サイト生成・アイコン生成）、dev_server.py、fetch_pyodide.py
tests/      pytest
```
