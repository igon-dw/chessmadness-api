# chessmadness-api

FastAPI によるチェス反復学習アプリのバックエンド API。

## 概要

**chessmadness** は、ドリル・反復学習に特化したローカル完結型のチェス学習アプリケーションです。

`chessmadness-api` はビジネスロジック層を担当し、以下を提供します:

- **データ管理:** ラインとテーマの CRUD API
- **PGNインポート:** 分岐の自動展開とデータ構造への変換
- **FEN検索:** 局面横断的なデータ抽出
- **学習進捗管理:** 反復学習のスケジュール情報
- **LLM連携:** chess-llm-bridge との統合

## プロジェクト構成

```
chessmadness/
├── chessmadness-ui/           # React フロントエンド
├── chessmadness-api/          # このリポジトリ
└── chessmadness-llm-bridge/   # Ollama連携・画像抽出
```

詳細は [chessApp-specs.md](./chessApp-specs.md) を参照。

## 仕様書

完全な仕様書・設計思想は同梱の `chessApp-specs.md` をご覧ください。

- 反復学習アプリとしての設計原則
- SQLiteスキーマ（テーマ・ライン・FENインデックス）
- PGNインポートフロー
- API エンドポイント設計
- チェスロジック（python-chess 統合）

## 技術スタック

- **フレームワーク:** FastAPI
- **言語:** Python 3.12
- **チェスロジック:** python-chess
- **データストア:** SQLite
- **パッケージ管理:** uv
- **非同期:** asyncio / asyncpg（予定）

## 開発環境構築

### 前提条件

- Python 3.12+
- uv（Pythonパッケージマネージャー）

### インストール

```bash
cd chessmadness-api
uv venv
source .venv/bin/activate  # Linux/macOS
# または
.venv\Scripts\activate  # Windows
uv pip install -r requirements.txt
```

### 開発サーバーの起動

```bash
uvicorn app.main:app --reload
```

APIドキュメント: `http://localhost:8000/docs`

## データベーススキーマ

SQLite スキーマは仕様書に詳細に記載。主要テーブル:

- `themes`: テーマ（再帰的階層構造）
- `lines`: ラインデータ（一本道の手順）
- `theme_lines`: テーマとラインの多対多関連
- `fen_index`: 全中間局面のキャッシュ
- `review_progress`: 反復学習の進捗管理
- `import_history`: インポート元の追跡

## API エンドポイント

### ラインの操作

- `GET /api/lines` — 全ライン取得
- `POST /api/lines` — ライン登録
- `GET /api/lines/{line_id}` — ライン詳細取得
- `PUT /api/lines/{line_id}` — ライン編集
- `DELETE /api/lines/{line_id}` — ライン削除

### テーマの操作

- `GET /api/themes` — 全テーマ取得
- `POST /api/themes` — テーマ作成
- `GET /api/themes/{theme_id}/lines` — テーマ配下のライン取得（子テーマ含む）
- その他 CRUD

### PGNインポート

- `POST /api/import/pgn` — PGNファイルをアップロードしてインポート

### FEN検索

- `GET /api/fen/{fen_string}` — 特定FENに到達するラインと次の手を検索

### 学習機能

- `GET /api/review/today` — 今日復習すべきラインを取得
- `POST /api/review/report` — 学習結果をレポート

詳細は開発時にOpenAPIドキュメントを参照。

## LLM連携

`chess-llm-bridge` と連携し、画像から棋譜を自動抽出。

```python
from chess_llm_bridge import extract_pgn_from_image

pgn_data = extract_pgn_from_image("path/to/image.png")
# ↓ PGNインポートAPIへ
```

## ライセンス

TBD

## 参考資料

- [プロジェクト仕様書](./chessApp-specs.md)
- [chessmadness-ui](https://github.com/igon-dw/chessmadness-ui)
- [chessmadness-llm-bridge](https://github.com/igon-dw/chessmadness-llm-bridge)
