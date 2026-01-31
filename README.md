# url-block-Pomodoro-Timer

クローム拡張を使わずに、ポモドーロタイマー実行中だけ指定したURLをブロックする簡易アプリです。
OS の hosts ファイルを書き換えるため、Chrome/Edge/Firefox などブラウザに依存せずにブロックできます。

> **注意**
> - hosts ファイルの編集には管理者権限が必要です。
> - 既存の hosts ファイルはバックアップし、終了時に元へ戻します。

## 使い方 (GUI)

```bash
python3 pomodoro_blocker.py
```

- アプリ画面で集中時間、休憩時間、サイクル数、ブロックしたいURLを設定できます。
- スタート後はセッション終了まで設定を変更できないようにロックします。
- 次回起動時に **最後に入力した時間とURLが自動で復元**されます。

### 管理者権限での起動（Windows / macOS / Linux）

hosts ファイルを書き換えるため、**管理者権限** が必要です。

**Windows**

1. スタートメニューで「PowerShell」または「コマンドプロンプト」を検索
2. 右クリック → **「管理者として実行」**
3. プロジェクトのフォルダへ移動して実行

```powershell
python pomodoro_blocker.py
```

**macOS / Linux**

```bash
sudo python3 pomodoro_blocker.py
```

## ブロックされない時のチェックポイント

1. **管理者権限で起動できているか**  
   hosts ファイルの編集は管理者権限が必須です。
2. **`www.` 付きのドメインも必要か**  
   `example.com` を入力しても、実際には `www.example.com` にアクセスしている場合があります。  
   このアプリでは **`example.com` を入力すると `www.example.com` も自動でブロック**します。
3. **DNS キャッシュ**  
   hosts を更新しても、OS やブラウザが古い情報を持っていると反映されないことがあります。  
   アプリは起動時に DNS キャッシュのフラッシュを試みますが、うまくいかない場合は PC 再起動が確実です。
4. **ブラウザの DNS オーバー HTTPS (DoH)**  
   一部ブラウザは OS の DNS を使わずに独自の DNS を使うことがあります。  
   その場合はブラウザ設定で **「セキュア DNS / DoH」** を無効にしてください。
5. **hosts ファイルが本当に更新されているか**  
   `# POMODORO_BLOCK_START` 〜 `# POMODORO_BLOCK_END` の間にブロック対象が書き込まれているか確認してください。
6. **ブラウザの再起動 / シークレットウィンドウ**  
   既存タブの DNS が固定されている場合があるため、ブラウザを再起動するかシークレットウィンドウで試してください。

## 使い方 (CLI)

```bash
python3 pomodoro_blocker.py --domain example.com --domain news.example.com
```

### オプション

- `--focus`: 集中時間 (分)。デフォルト 25。
- `--break`: 休憩時間 (分)。デフォルト 5。
- `--cycles`: サイクル数。デフォルト 4。
- `--domain`: ブロックしたいドメイン (複数指定可)。
- `--domains-file`: ドメイン一覧のファイル (1 行 1 ドメイン)。
- `--hosts`: hosts ファイルのパスを上書き。
- `--dry-run`: hosts ファイルを変更せずに動作確認。

### 例

```bash
sudo python3 pomodoro_blocker.py \
  --focus 50 \
  --break 10 \
  --cycles 2 \
  --domain youtube.com \
  --domain twitter.com
```

## 使っている技術とブロックの仕組み（初心者向け）

### 使っている技術

- **Python**: タイマー処理と UI をまとめて実装しています。
- **Tkinter (ティーケーインター)**: Python 標準の GUI ライブラリ。追加インストール不要で画面を作れます。
- **hosts ファイル**: OS がドメイン名を IP アドレスへ変換するときに参照する仕組みです。

### hosts ファイルって何？

ブラウザで `example.com` にアクセスする時、まず **「このドメインはどの IP アドレス？」** を OS が調べます。
そのとき最初に参照されるのが `hosts` ファイルです。ここに以下のような行があると、
`example.com` は **127.0.0.1（自分自身）** に向けられてしまい、結果としてアクセスできなくなります。

```
127.0.0.1 example.com
```

この方法は **ブラウザに依存しない** ため、Chrome/Edge/Firefox などどのブラウザでもブロックが効きます。

### どうやってブロックしているの？

- セッション開始時に `hosts` ファイルへ **専用のブロック領域** を追加します。
  追加位置は `# POMODORO_BLOCK_START` と `# POMODORO_BLOCK_END` の間です。
- セッション終了時に、そのブロック領域を削除し、**元の状態に復元**します。
- 事故防止のため、開始前に **バックアップ** を作成し、終了時に元へ戻します。

### 安全のための挙動

- GUI で「開始」したあとは、セッションが終わるまで **設定を変更できない** ようにロックします。
- `hosts` ファイルは管理者権限が必要なため、エラー時はメッセージを表示します。

### 仕組みまとめ

1. GUI で「集中時間」「休憩時間」「URL」を設定  
2. 開始と同時に `hosts` にブロックを追加  
3. タイマーが終了すると `hosts` を元に戻す  

これにより **ブラウザ拡張なしでも確実にブロック**できます。

## exe 化（Windows向け）

Python が入っていない PC でも起動できるようにするには、`PyInstaller` で exe を作成します。

```powershell
pip install pyinstaller
pyinstaller --onefile --noconsole pomodoro_blocker.py
```

- 生成された exe は `dist/pomodoro_blocker.exe` に出力されます。
- 管理者権限が必要なため、exe も **「管理者として実行」** してください。
- `pyinstaller` が見つからない場合は、次のように **Python 経由で実行**してください。

```powershell
python -m PyInstaller --onefile --noconsole pomodoro_blocker.py
```

### manifest（UAC 設定）とは？

Windows の exe には「**このアプリは管理者権限を要求するか**」を示す設定を埋め込めます。  
これが **manifest（マニフェスト）** で、UAC（ユーザーアカウント制御）の動作を決めます。

#### できること

- 起動時に **自動で管理者権限を要求（UAC ダイアログを表示）** させる

#### PyInstaller での指定例

```powershell
pyinstaller --onefile --noconsole --uac-admin pomodoro_blocker.py
```

このオプションを付けてビルドすると、exe 起動時に **管理者権限を要求するダイアログ** が表示されます。
