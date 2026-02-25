# プロジェクト仕様書: Chess Repertoire Trainer (仮)

最終更新: 2026/02/25（スキルブロックシステム・錆システム・得意武器・実戦解析の仕様を追加）

---

## 1. プロジェクト概要

### 1.1 目的

チェスの反復学習（Spaced Repetition）に特化したローカル完結型アプリケーション。

書籍・教材コンテンツ（スクリーンショット・スキャン画像・PGNファイル）から棋譜を取り込み、
独自のデータ構造で管理し、反復練習を通じてレパートリーを定着させることを主眼とする。

本プロジェクトは **Scid や ChessX の単なる代替ではない**。
既存のデータベースソフトウェアが「対局データの蓄積と検索」を目的とするのに対し、
本プロジェクトは **「手筋（ライン）の記憶定着」** を目的とする学習アプリケーションである。

さらに本プロジェクトは、単なる暗記ツールにとどまらず、**スキルツリー・錆システム・実戦解析**を
組み合わせることで、ユーザーが自分だけのチェスアイデンティティを育てるプラットフォームを目指す。
学んだラインはゲームのスキルツリーのように枝分かれして可視化され、実戦との照合で
「錆びている」スキルが自動検出され、習熟したラインは「得意武器（Signature Weapon）」として昇華する。

### 1.2 Chessableとの差異

Chessableは優れた反復学習プラットフォームだが、以下の制約がある:

- クラウドサービスへの依存（オフライン不可）
- 購入コンテンツ以外の自由なインポートが制限的
- 書籍・紙媒体の教材を直接取り込めない
- データのエクスポート・バックアップが限定的

本プロジェクトはこれらの制約を解消し、**ローカル環境で完全に自己完結する**学習ツールを目指す。

### 1.3 サブプロジェクト構成

| サブプロジェクト   | 役割                                                          |
| ------------------ | ------------------------------------------------------------- |
| `chess-ui`         | React + TypeScript によるフロントエンド（盤面操作・学習UI）   |
| `chess-api`        | FastAPI によるバックエンドAPI（データ管理・ビジネスロジック） |
| `chess-llm-bridge` | Ollama連携・画像からのPGN/FEN抽出・バリデーション             |

```
chess-app/
├── chess-ui/            # React + TypeScript + Vite
├── chess-api/           # FastAPI (Python)
├── chess-llm-bridge/    # Ollama連携 (Python パッケージ)
├── docker-compose.yml
└── README.md
```

`chess-llm-bridge` は独立したPythonパッケージとして実装し、
`chess-api` から直接 import して使用する。IPC（プロセス間通信）は不要。

---

## 2. 設計思想

### 2.1 反復学習ファーストの設計

本アプリケーションのすべての設計判断は「反復学習を効率的に行えるか」を基準とする。
データベースの網羅性や検索性能は二の次であり、
**学習者が1本のラインを繰り返し練習し、記憶に定着させる体験** が最優先である。

### 2.2 ラインの一本道原則

チェスの棋譜（PGN）は分岐（バリエーション）を含むことができる。
しかし反復学習においては、分岐を含む棋譜は学習単位として不適切である。

**理由:**

- 学習者は「ある局面で何を指すべきか」を1手ずつ記憶する必要がある
- 分岐があると「この局面からはAもBもある」という曖昧さが生じ、記憶の定着を妨げる
- Chessableが成功している理由の一つは、ラインを一本道として提示している点にある

**原則:**

- PGNファイルの分岐は、インポート時に展開してそれぞれ独立したラインとして保存する
- 例: 2手目で `e5` と `d5` に分岐するPGNは、`(e4, e5)` と `(e4, d5)` の2つのラインになる
- `e4 e5 Nf3 Nc6` と `e4 e5` は手数が異なるだけだが、別のラインとして扱う
  - 前者は King's Knight Game の形を覚えるテーマ
  - 後者は King's Pawn Game という形を覚えるテーマ
  - **学習目的が異なるものは、データとしても別物である**

### 2.3 FEN別管理による局面横断

異なる手順であっても同一局面に到達することがある。
例えば `e4 e5 Nf3 Nf6` と `Nf3 Nf6 e4 e5` の最終局面は同一である。
これをFEN（Forsyth-Edwards Notation）で判定し、局面横断的なデータ抽出を可能にする。

**活用例:**

- 「この局面に至るすべてのラインを表示」
- 「この局面から次の手として最も多く登場する手は何か」
- 「この局面を含むラインの学習進捗はどうか」

**パフォーマンス方針:**

- 毎回ラインデータからFENを計算するのはコストが高い
- ライン登録時に python-chess で全手を再生し、各ply（半手）ごとのFENを事前計算して
  キャッシュテーブル（`fen_index`）に格納する
- これにより FEN 検索はインデックス参照のみとなり、リアルタイム計算は不要

### 2.4 階層的テーマ管理

PGNファイルを分割してラインに展開すると、数十〜数百のラインが生成される可能性がある。
これらはバラバラのデータではなく、元の書籍や教材において一つのテーマをもって構成されたものである。

**階層の例:**

```
Openings/
├── King's Pawn/
│   ├── Italian Game/
│   │   ├── Chapter 1: Giuoco Piano/
│   │   │   ├── Line 1: e4 e5 Nf3 Nc6 Bc4 Bc5
│   │   │   ├── Line 2: e4 e5 Nf3 Nc6 Bc4 Nf6
│   │   │   └── ...
│   │   └── Chapter 2: Evans Gambit/
│   │       └── ...
│   └── Ruy Lopez/
│       └── ...
Endgames/
├── Rook Endings/
│   ├── Lucena Position Drills/
│   │   └── ...
│   └── Philidor Position Drills/
│       └── ...
```

**設計判断: 固定階層ではなく再帰的階層を採用する**

学習コンテンツは必ずしも「カテゴリ → 書籍 → 章」の3階層に収まらない。

- 書籍に紐づかない自作のドリル集がありうる
- 動画講座のように章立てが書籍と異なる教材がありうる
- カテゴリの下に直接ラインを置きたいケースがありうる

そのため、**ファイルシステムのディレクトリのように自由にネストできる再帰的構造**を採用する。
テーブル設計は自己参照外部キー（`parent_id`）による隣接リストモデルとする。

### 2.5 データの堅牢性と重複管理

異なるPGNファイルから同一のラインがインポートされる場合がある。

**原則:**

- **完全に同一のライン**（同一の開始局面 + 同一の手順）は、`lines` テーブル上では1レコードのみ
- ただし、**同一ラインが異なるテーマに属すること**は許容する（多対多関連で表現）
- 例: `e4 e5 Nf3 Nc6 Bc4` は「Italian Game入門」テーマと「1.e4 レパートリー構築」テーマの
  両方に属してよい
- インポート元（どのPGNファイルから来たか、LLM抽出か手動入力か）は `import_history` で追跡
- 重複インポート時は、既存ラインへの参照を追加するのみで、データの二重登録は行わない

**学習進捗の独立性:**

- 反復学習の進捗は「テーマ × ライン」の組み合わせごとに独立して管理する
- 同じラインでもテーマAでは習熟済み、テーマBでは未学習という状態がありうる
- これは意図的な設計であり、テーマごとの学習文脈を尊重するためである

### 2.6 非標準開始局面のサポート

すべてのラインが標準初期配置（`rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`）
から始まるわけではない。

**対応が必要なケース:**

- エンドゲームドリル（例: K+R vs K の特定局面からの手順）
- タクティクス問題（中盤の特定局面からの最善手順）
- 特定のオープニング局面からのバリエーション練習

各ラインは `start_fen` フィールドを必ず持ち、開始局面を明示する。
`fen_index` テーブルの ply=0 は常に `start_fen` と一致する。

---

## 3. コンプライアンス

### 3.1 著作権への配慮

- **個人利用の徹底:** 抽出データは個人学習目的に限定する
- **事実の抽出:** 書籍・教材の創作物（解説文・図版デザイン・UI要素）ではなく、
  客観的事実（棋譜・駒の配置）の抽出のみを目的とする
- チェスの棋譜は著作権法上「事実の記録」であり創作物ではないとされるが、
  解説文やレイアウトは創作物であるため、これらの抽出・保存は行わない

**スキルブロック共有機能について:**

- ユーザーが自ら作成・定義したスキルブロック（局面FEN + 手順 + メタデータ）の共有コード生成機能を提供する
- 共有コードに含まれるのは「局面の状態（FEN）」「手順」「ユーザー定義のメタデータ（名前・タグ・説明）」のみ
- 書籍・教材の解説文・解説コンテンツは含まれない
- ただし、共有されるスキルブロックの内容（手順の出典等）に関する著作権上の責任は
  **スキルブロックの作成者が負う**。本システムはその内容の合法性を保証しない
- この責任区分はインターネット上に公開されているPGNデータの共有慣行と同等の扱いとする

### 3.2 データプライバシー

- 画像データおよび抽出テキストを外部サーバーに送信しない
- LLM推論はOllama経由でローカル実行を強制する
- ネットワーク通信はローカルホスト内（フロントエンド ↔ バックエンド間）のみ

---

## 4. 開発・実行環境

- **OS:** Linux (EndeavourOS / Arch-based)
- **CPU:** AMD Ryzen 5 7600
- **GPU:** AMD Radeon RX 7600 (VRAM 8GB)
- **加速ライブラリ:** ROCm (Ollama 経由)
- **推論エンジン:** Ollama (Local LLM)
- **使用モデル候補:** Llama 3.2-Vision (11B) または Moondream2 (1.6B)
- **コンテナ:** Docker / docker-compose

---

## 5. 技術スタック

### 5.1 一覧

| 項目                    | 採用技術                    | 採用理由                                                                                                                           |
| ----------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| フロントエンド          | React + TypeScript + Vite   | 市場シェア最大のUIライブラリ。コンポーネント指向・宣言的UIのメンタルモデルは他フレームワークにも通じる基盤概念。キャリア価値が高い |
| チェス盤UI              | react-chessboard + chess.js | クライアント側で合法手判定を即座に実行可能。サーバー通信なしで駒移動が完結し、盤面操作が軽快                                       |
| バックエンドAPI         | FastAPI (Python)            | 非同期I/O標準対応。Pydanticによる型安全。OpenAPIドキュメント自動生成。ML/AIバックエンドの事実上の標準                              |
| チェスロジック          | python-chess                | PGN/FENパース、合法手判定、バリデーション、FEN生成を網羅。最も成熟したPython用チェスライブラリ                                     |
| データストア            | SQLite (FTS5)               | ファイル1個で完結。再帰クエリ（WITH RECURSIVE）対応。全文検索機能付き                                                              |
| LLM連携                 | Ollama                      | ローカルLLM推論。ROCm対応でAMD GPU活用可能                                                                                         |
| パッケージ管理 (Python) | uv                          | 高速・モダンなPythonパッケージマネージャー                                                                                         |
| パッケージ管理 (JS)     | npm または pnpm             | フロントエンド依存管理                                                                                                             |
| コンテナ                | Docker / docker-compose     | バックエンド + フロントエンドの一括デプロイ                                                                                        |

### 5.2 技術選定の背景

#### なぜ PyQt6 / PySide6 ではなく Web UI か

当初 PyQt6 による GUI を検討したが、以下の理由で Web ベースに移行した:

- **デスクトップ環境依存の排除:** Qt/GTKのバージョン問題、ディスプレイサーバー差異（X11/Wayland）を回避
- **コンテナ化の容易さ:** Pythonバックエンドをコンテナに入れてブラウザからアクセスする構成が自然
- **追加パッケージの不要化:** ユーザのシステムにQt6等を強いる必要がない（ブラウザさえあれば動作）
- **チェスUI資産の豊富さ:** chessboard.js / chess.js / react-chessboard など、Web向けチェスUIの成熟度が圧倒的に高い
- **盤面操作の軽快さ:** chess.jsはブラウザ内で動作し、合法手判定もクライアント側で即座に完了する。サーバー通信を待たずに駒をドラッグ&ドロップできる

#### 合法手判定の二重チェック

チェスのルール判定は自前で実装せず、実績のあるOSSライブラリに委ねる:

- **フロントエンド (chess.js):** 即応性のため。駒のドラッグ中にリアルタイムで合法手を判定し、不正な移動を即座にブロックする
- **バックエンド (python-chess):** データ保存時の正式バリデーション。PGNインポート時のルール検証、FEN生成、fen_index構築に使用

この二重チェックは冗長だが、フロントの軽快さとバックエンドの信頼性を両立するために意図的に採用している。

#### なぜ Go でも Rust でもなく Python か

- python-chess がチェスロジックライブラリとして圧倒的に成熟している（PGNパーサー、FEN生成、合法手判定、バリエーション展開すべて完備）
- Go のチェスライブラリ（notnil/chess等）はメンテナンス・機能面で python-chess に及ばない
- Rustのchess crateは高速だがエコシステムがPythonに劣る
- Ollama連携、画像処理（Pillow）、データ処理のライブラリもPythonが最も充実している
- FastAPIにより、Pythonの弱点である速度もasync/awaitで補える

---

## 6. アーキテクチャ

### 6.1 全体構成図

```
┌─────────────────────────────────────────────────┐
│  Browser (Chrome, Firefox, etc.)                │
│  ┌───────────────────────────────────────────┐  │
│  │ chess-ui (React + TypeScript + Vite)      │  │
│  │  - react-chessboard: 盤面描画・駒移動     │  │
│  │  - chess.js: クライアント側合法手判定      │  │
│  │  - 学習UI: 反復練習・進捗表示             │  │
│  │  - テーマ管理UI: 階層ツリー操作           │  │
│  │  - スキルツリーUI: グラフ可視化           │  │
│  │  - 錆ダッシュボード: 忘却・実戦連動表示   │  │
│  └──────────────┬────────────────────────────┘  │
└─────────────────┼───────────────────────────────┘
                  │ HTTP REST / WebSocket
┌─────────────────┼───────────────────────────────┐
│  chess-api      │  (FastAPI)                    │
│  ┌──────────────┴────────────────────────────┐  │
│  │ REST API                                  │  │
│  │  - ライン CRUD                             │  │
│  │  - テーマ階層 CRUD                          │  │
│  │  - FEN検索                                 │  │
│  │  - PGNインポート（分岐展開→ライン分割）     │  │
│  │  - 反復学習セッション管理                   │  │
│  │  - スキルブロック CRUD + 自動グラフ連結     │  │
│  │  - 実戦PGN解析（FENハッシュマッチング）    │  │
│  │  - 錆レベル算出・得意武器スコアリング      │  │
│  │  - スキルブロック共有コード生成・取込       │  │
│  ├───────────────────────────────────────────┤  │
│  │ python-chess                              │  │
│  │  - PGN/FEN パース・バリデーション           │  │
│  │  - fen_index 生成（全中間局面展開）         │  │
│  │  - インポート時の分岐展開                   │  │
│  │  - FEN正規化（4フィールド）                │  │
│  ├───────────────────────────────────────────┤  │
│  │ chess-llm-bridge (Python パッケージ)      │  │
│  │  - Ollama API 呼び出し                     │  │
│  │  - 画像→PGN/FEN 抽出                      │  │
│  │  - バリデーション・自己修復ループ           │  │
│  ├───────────────────────────────────────────┤  │
│  │ SQLite                                    │  │
│  │  - 全データ格納                            │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  ★ Docker container で配布可能                   │
└─────────────────────────────────────────────────┘
```

### 6.2 通信方式

- **REST API (HTTP):** ライン・テーマの CRUD、PGNインポート、FEN検索など
- **WebSocket:** LLM処理の進捗通知（長時間処理のリアルタイムフィードバック）

### 6.3 軽快さの確保

盤面操作（駒の移動・合法手ハイライト）はフロントエンド内で完結し、サーバー通信を伴わない。
ユーザが体感する「もっさり感」は以下の場合にのみ発生しうる:

- **許容:** LLM推論中の待機、大量データのインポート処理
- **不許容:** 駒のドラッグ、ラインの再生、盤面の切り替え

これを実現するため:

1. chess.js がブラウザ内で合法手判定を行い、不正な駒移動を即座にブロック
2. ラインデータはAPIから取得後にフロントエンドのメモリ上にキャッシュ
3. fen_index によりFEN検索はバックエンドでもインデックス参照のみ（リアルタイム計算なし）

---

## 7. データモデル

### 7.1 設計原則

1. **ラインは一本道:** 分岐を含まない手順の列。PGNの分岐はインポート時に展開する
2. **ラインの一意性:** 同一の `(start_fen, moves)` の組み合わせは1レコードのみ
3. **テーマとラインは多対多:** 同一ラインが複数テーマに属することを許容する
4. **FENは事前計算:** 全中間局面のFENをキャッシュし、検索を高速化する
5. **学習進捗はテーマ×ラインごと:** 同じラインでもテーマが異なれば進捗は独立
6. **開始局面は可変:** エンドゲームドリル等のため `start_fen` を必ず保持する
7. **スキルブロックはラインのラッパー:** `lines` テーブルの1レコードに対して最大1つの `skill_blocks` レコードが存在する。スキルブロックはユーザー定義のメタデータ（名前・タグ・説明）とゲーミフィケーション情報を付与する層
8. **テーマとスキルブロックは独立した概念:** テーマは「学習の整理棚」（人間の分類）、スキルブロックグラフは「局面の因果関係」（FENの連続性）。両者は独立して存在し、同じラインが両方に属してよい
9. **錆レベルは保存しない:** 時間減衰は連続的に変化するため、`rust_level` は毎回計算する。計算に必要な入力値（`last_success_at` 等）のみ保存する
10. **実戦照合はエンジン不要:** 実戦PGNとスキルブロックの照合は純粋なFEN文字列の一致判定のみで行う。エンジン評価値は不要

### 7.2 SQLite スキーマ

````sql
-- ================================================================
-- テーマ階層（再帰的、ディレクトリのように自由にネスト可能）
-- ================================================================
--
-- 隣接リストモデルによる自己参照テーブル。
-- parent_id が NULL のノードがルート（最上位テーマ）。
-- SQLite の WITH RECURSIVE クエリで任意のサブツリーを取得可能。
--
-- 使用例:
--   Openings (parent_id=NULL)
--     └─ King's Pawn (parent_id=1)
--         ├─ Italian Game (parent_id=2)
--         │   ├─ Chapter 1: Giuoco Piano (parent_id=3)
--         │   └─ Chapter 2: Evans Gambit (parent_id=3)
--         └─ Ruy Lopez (parent_id=2)
--   Endgames (parent_id=NULL)
--     └─ Rook Endings (parent_id=6)
--         ├─ Lucena Position (parent_id=7)
--         └─ Philidor Position (parent_id=7)

CREATE TABLE themes (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES themes(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_themes_parent ON themes(parent_id);

-- ================================================================
-- ライン（一本道の手筋、本アプリのコアデータ）
-- ================================================================
--
-- 分岐を含まない手順の列。PGNの分岐はインポート時に展開される。
--
-- moves: SAN形式の手順をスペース区切りで格納。
--        例: "e4 e5 Nf3 Nc6 Bc4 Bc5"
--
-- start_fen: ラインの開始局面。標準初期配置でない場合がある
--            （エンドゲームドリル、タクティクス問題など）。
--
-- final_fen: ラインの最終局面のFEN。fen_indexからも取得可能だが、
--            頻繁に参照されるため非正規化して保持する。
--
-- move_count: 手数。検索・フィルタ用。
--
-- UNIQUE制約: 同一開始局面から同一手順のラインは1レコードのみ。
--             異なるテーマへの紐付けは theme_lines で表現する。

CREATE TABLE lines (
    id          INTEGER PRIMARY KEY,
    moves       TEXT NOT NULL,
    move_count  INTEGER NOT NULL,
    start_fen   TEXT NOT NULL DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    final_fen   TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(start_fen, moves)
);

CREATE INDEX idx_lines_start_fen ON lines(start_fen);
CREATE INDEX idx_lines_final_fen ON lines(final_fen);

-- ================================================================
-- テーマとラインの多対多関連
-- ================================================================
--
-- 同じラインが複数テーマに属することを許容する。
-- sort_order はテーマ内でのラインの表示順序。
-- note はテーマ固有のメモ（例: "このラインは白番の主力変化"）。
--
-- 例: ライン "e4 e5 Nf3 Nc6 Bc4" が以下に属する場合:
--   - theme "Italian Game入門" (sort_order=1)
--   - theme "1.e4 レパートリー" (sort_order=15)
-- → theme_lines に2レコード挿入。lines テーブルは1レコードのまま。

CREATE TABLE theme_lines (
    id          INTEGER PRIMARY KEY,
    theme_id    INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    UNIQUE(theme_id, line_id)
);

CREATE INDEX idx_theme_lines_theme ON theme_lines(theme_id);
CREATE INDEX idx_theme_lines_line ON theme_lines(line_id);

-- ================================================================
-- FENインデックス（全中間局面のキャッシュ）
-- ================================================================
--
-- ライン登録時に python-chess で全手を再生し、
-- 各 ply（半手）ごとのFENと次の手を事前計算して格納する。
--
-- ply: 何手目か。0 = 開始局面（start_fen と一致）。
-- fen: その時点の盤面状態（FEN文字列）。
-- next_move: その局面から次に指す手（SAN形式）。最終局面では NULL。
--
-- 具体例: ライン "e4 e5 Nf3 Nc6" の場合
--
-- | ply | fen                                              | next_move |
-- |-----|--------------------------------------------------|-----------|
-- |   0 | rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR ... | e4        |
-- |   1 | rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR...| e5        |
-- |   2 | rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR.| Nf3       |
-- |   3 | rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB.| Nc6       |
-- |   4 | r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQ.| NULL      |
--
-- データ量の見積もり:
--   - 1ラインが平均20手 → 21行（開始局面含む）
--   - 1000ライン → 約21,000行
--   - FEN文字列 ≈ 70バイト + next_move ≈ 5バイト = 約75バイト/行
--   - 21,000行 × 75バイト ≈ 約1.6MB
--   - インデックス込みでも数十MB以内に収まり、SQLite で問題なく処理可能
--
-- 更新タイミング:
--   - ライン登録時: python-chess で全手を順に適用し一括INSERT
--   - ライン削除時: ON DELETE CASCADE で自動クリーンアップ
--   - ライン編集時: 該当ラインの fen_index を全削除→再生成

CREATE TABLE fen_index (
    id          INTEGER PRIMARY KEY,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    ply         INTEGER NOT NULL,
    fen         TEXT NOT NULL,
    next_move   TEXT,
    UNIQUE(line_id, ply)
);

CREATE INDEX idx_fen_lookup ON fen_index(fen);
CREATE INDEX idx_fen_next ON fen_index(fen, next_move);

-- ================================================================
-- 反復学習の進捗管理
-- ================================================================
--
-- 学習進捗は「テーマ × ライン」の組み合わせ（theme_lines）ごとに独立。
-- 同じラインでもテーマが異なれば進捗は別管理。
--
-- SRSアルゴリズム（SM-2 / FSRS 等）の選定は未確定のため、
-- 汎用的なカラムのみを定義し、アルゴリズム固有のパラメータは
-- 決定後に追加する。

```sql
-- ================================================================
-- review_progress の実装注記
-- ================================================================
-- spec当初は ease_factor 等をアルゴリズム確定後に追加予定としていたが、
-- SM-2を採用したため ease_factor カラムが追加済み（実装済み）。
-- UNIQUE(theme_line_id) により theme×line ごとに独立した進捗を保持。

CREATE TABLE review_progress (
    id              INTEGER PRIMARY KEY,
    theme_line_id   INTEGER NOT NULL REFERENCES theme_lines(id) ON DELETE CASCADE,
    interval_days   INTEGER NOT NULL DEFAULT 0,
    repetitions     INTEGER NOT NULL DEFAULT 0,
    ease_factor     REAL    NOT NULL DEFAULT 2.5,
    next_review     TEXT,
    last_reviewed   TEXT,
    UNIQUE(theme_line_id)
);

-- ================================================================
-- インポート履歴
-- ================================================================
--
-- あるラインがどこから取り込まれたかを追跡する。
-- 同じラインが複数のソースからインポートされた場合、複数レコードが存在する。
--
-- origin_type:
--   - 'pgn_file': PGNファイルからのインポート
--   - 'llm_extraction': chess-llm-bridge による画像からの抽出
--   - 'manual': ユーザの手動入力
--
-- origin_ref: ファイルパス、ページ番号、画像ファイル名など。

CREATE TABLE import_history (
    id          INTEGER PRIMARY KEY,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    origin_type TEXT NOT NULL CHECK(origin_type IN ('pgn_file', 'llm_extraction', 'manual')),
    origin_ref  TEXT,
    imported_at TEXT DEFAULT (datetime('now'))
);
```

### 7.2.1 スキルブロックシステムのスキーマ

スキルブロックシステムは既存テーブルに**一切変更を加えない**独立した追加レイヤーとして設計する。

```sql
-- ================================================================
-- スキルブロック（lines テーブルのラッパー）
-- ================================================================
--
-- lines テーブルの1レコードに対して最大1つのスキルブロックが存在する
-- （UNIQUE(line_id) 制約）。
--
-- テーマシステムと完全分離した独立レイヤー。
-- テーマは「学習の整理棚」（人間の分類）、
-- スキルブロックは「局面の因果関係グラフ」（FENの連続性）を表す。
--
-- source_type:
--   'original'  — ユーザーが自ら作成
--   'imported'  — 他者の共有コードから取込
--   'forked'    — 既存ブロックを末端から延長して派生
--
-- share_code: "chessmadness:XXXXX" 形式の共有コード（未共有時 NULL）。
--             内容は JSON→zlib圧縮→Base64 でエンコードされる。
--
-- forked_from_id: fork元のスキルブロックID（forkでない場合 NULL）。
--                 fork元が削除された場合は ON DELETE SET NULL で NULL になる。

CREATE TABLE skill_blocks (
    id              INTEGER PRIMARY KEY,
    line_id         INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    tags            TEXT,           -- JSON配列 e.g. '["italian","trap","sacrifice"]'
    source_type     TEXT NOT NULL DEFAULT 'original'
                    CHECK(source_type IN ('original', 'imported', 'forked')),
    share_code      TEXT UNIQUE,
    forked_from_id  INTEGER REFERENCES skill_blocks(id) ON DELETE SET NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(line_id)
);

CREATE INDEX idx_skill_blocks_line ON skill_blocks(line_id);
CREATE INDEX idx_skill_blocks_share ON skill_blocks(share_code);

-- ================================================================
-- スキルリンク（FENベースの有向グラフ）
-- ================================================================
--
-- スキルブロック間の「前後関係」を局面（FEN）で自動的に連結する。
--
-- link_fen: 2つのブロックをつなぐ接続点の正規化FEN。
--           具体的には parent_block の final_fen = child_block の start_fen。
--           FEN正規化は4フィールド（局面・手番・キャスリング・アンパッサン）で行い、
--           half-move clock と full-move number は無視する。
--
-- link_type:
--   'auto'   — システムがブロック登録時に自動検出・生成
--   'manual' — ユーザーが明示的に指定
--
-- 新規スキルブロック登録時の自動連結ロジック:
--   1. 新ブロックの start_fen に一致する final_fen を持つ既存ブロックを探す → 親
--   2. 新ブロックの final_fen に一致する start_fen を持つ既存ブロックを探す → 子
--   3. 発見した全ての親子関係を skill_links に INSERT (link_type='auto')

CREATE TABLE skill_links (
    id              INTEGER PRIMARY KEY,
    parent_block_id INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    child_block_id  INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    link_fen        TEXT NOT NULL,
    link_type       TEXT NOT NULL DEFAULT 'auto'
                    CHECK(link_type IN ('auto', 'manual')),
    UNIQUE(parent_block_id, child_block_id)
);

CREATE INDEX idx_skill_links_parent ON skill_links(parent_block_id);
CREATE INDEX idx_skill_links_child ON skill_links(child_block_id);
CREATE INDEX idx_skill_links_fen ON skill_links(link_fen);

-- ================================================================
-- スキル習熟度（ゲーミフィケーション + 錆システム入力値）
-- ================================================================
--
-- 各スキルブロックの習熟状態を管理する。
-- review_progress がテーマ×ライン単位の学習スケジュール管理を担うのに対し、
-- skill_mastery はスキルブロック単位のゲーミフィケーション状態と
-- 錆計算のための入力値を保持する。
--
-- rust_level（錆レベル）は保存しない。毎回以下の入力値から計算する:
--   - last_success_at + interval_days → 時間減衰
--   - last_game_miss_at vs last_success_at → 実戦での「ど忘れ」検出
--
-- 錆レベル計算結果（参考、コード内の compute_rust_level 関数で算出）:
--   'fresh'    — last_success から interval 以内
--   'aging'    — last_success から interval × 1.5 超過
--   'rusty'    — last_success から interval × 3.0 超過、または未練習
--   'critical' — last_game_miss_at > last_success_at（実戦でのど忘れ）
--
-- weapon_score: 「得意武器スコア」。以下の式で計算し保存する（イベント駆動で更新）:
--   score = log(1 + perfect_runs + game_matches*2)
--           * (0.4 + 0.6 * (game_matches / (game_matches + game_misses)))
--           * exp(-0.023 * days_since_success)
--
-- is_signature: weapon_score が閾値（TBD、初期値 3.0）を超えたら 1 に設定。
--
-- signature_title: ユーザー自身が設定する「得意武器の二つ名」。LLMは使用しない。

CREATE TABLE skill_mastery (
    id                INTEGER PRIMARY KEY,
    skill_block_id    INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    -- ゲーミフィケーション
    xp                INTEGER NOT NULL DEFAULT 0,
    level             INTEGER NOT NULL DEFAULT 1,
    streak            INTEGER NOT NULL DEFAULT 0,
    max_streak        INTEGER NOT NULL DEFAULT 0,
    perfect_runs      INTEGER NOT NULL DEFAULT 0,
    -- 錆計算の入力値
    last_success_at   TEXT,           -- 最終成功日時（レビュー or 実戦 match）
    last_game_miss_at TEXT,           -- 最終実戦 miss 日時
    game_matches      INTEGER NOT NULL DEFAULT 0,
    game_misses       INTEGER NOT NULL DEFAULT 0,
    -- 得意武器
    weapon_score      REAL NOT NULL DEFAULT 0.0,
    is_signature      INTEGER NOT NULL DEFAULT 0,  -- Boolean: 0 or 1
    signature_title   TEXT,           -- ユーザー定義の二つ名
    UNIQUE(skill_block_id)
);

CREATE INDEX idx_skill_mastery_block ON skill_mastery(skill_block_id);
CREATE INDEX idx_skill_mastery_signature ON skill_mastery(is_signature);
CREATE INDEX idx_skill_mastery_weapon ON skill_mastery(weapon_score DESC);

-- ================================================================
-- 実戦ゲーム（手動PGN投入）
-- ================================================================
--
-- ユーザーが手動で投入した実戦棋譜を管理する。
-- Local-only 原則を維持するため、外部API（Lichess/Chess.com）への
-- 自動取得機能は設けない。ユーザーがPGNテキストを手動でペーストする。
--
-- player_color: 解析対象のプレイヤーの手番。
--               この色の着手のみ skill_blocks との照合を行う。
--
-- 解析フロー（game_analyzer.py が担当）:
--   1. PGN を python-chess でパース
--   2. 各手番の局面FEN（正規化済み）を fen_index と照合
--   3. スキルブロックの「知っているはずの手」と実際の着手を比較
--   4. 一致 → 'match' イベント、不一致 → 'miss' イベントを game_skill_events に記録
--   5. 各スキルブロックの skill_mastery を更新（weapon_score 再計算含む）
--   6. 'miss' イベントがあるスキルブロックの review_progress に SM-2 部分減衰を適用

CREATE TABLE games (
    id            INTEGER PRIMARY KEY,
    player_color  TEXT NOT NULL CHECK(player_color IN ('white', 'black')),
    pgn           TEXT NOT NULL,
    opponent_name TEXT,
    played_at     TEXT,           -- PGN の Date ヘッダから取得（なければ NULL）
    analyzed_at   TEXT DEFAULT (datetime('now'))
);

-- ================================================================
-- ゲームとスキルブロックの照合イベント
-- ================================================================
--
-- event_type:
--   'match' — 知っているはずの局面で正しい手を指せた → 実戦成功
--   'miss'  — 知っているはずの局面で別の手を指した → 実戦でのど忘れ
--
-- expected_move: スキルブロックが定義する正解手（SAN形式）
-- actual_move:   実際に指した手（SAN形式）。match の場合は expected_move と同じ。

CREATE TABLE game_skill_events (
    id              INTEGER PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    skill_block_id  INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL CHECK(event_type IN ('match', 'miss')),
    fen             TEXT NOT NULL,
    expected_move   TEXT NOT NULL,
    actual_move     TEXT,
    ply             INTEGER NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_game_events_game ON game_skill_events(game_id);
CREATE INDEX idx_game_events_block ON game_skill_events(skill_block_id);
CREATE INDEX idx_game_events_type ON game_skill_events(event_type);
````

### 7.3 主要クエリパターン

```sql
-- ------------------------------------------------
-- テーマのサブツリーを再帰的に取得
-- ------------------------------------------------
-- "Italian Game" 配下のすべてのテーマ（子孫含む）を取得
WITH RECURSIVE subtree AS (
    SELECT id, name, parent_id, 0 AS depth
    FROM themes
    WHERE name = 'Italian Game'
    UNION ALL
    SELECT t.id, t.name, t.parent_id, s.depth + 1
    FROM themes t
    JOIN subtree s ON t.parent_id = s.id
)
SELECT * FROM subtree ORDER BY depth, sort_order;

-- ------------------------------------------------
-- テーマ配下の全ラインを取得（子テーマ含む）
-- ------------------------------------------------
WITH RECURSIVE subtree AS (
    SELECT id FROM themes WHERE id = :theme_id
    UNION ALL
    SELECT t.id FROM themes t
    JOIN subtree s ON t.parent_id = s.id
)
SELECT l.*, tl.sort_order, tl.note
FROM lines l
JOIN theme_lines tl ON tl.line_id = l.id
WHERE tl.theme_id IN (SELECT id FROM subtree)
ORDER BY tl.sort_order;

-- ------------------------------------------------
-- 特定局面から次に指せる手の一覧（全ラインから集約）
-- ------------------------------------------------
SELECT
    next_move,
    COUNT(DISTINCT line_id) AS line_count
FROM fen_index
WHERE fen = :target_fen
  AND next_move IS NOT NULL
GROUP BY next_move
ORDER BY line_count DESC;

-- ------------------------------------------------
-- 特定局面に至るすべてのラインを取得
-- ------------------------------------------------
SELECT DISTINCT l.*
FROM lines l
JOIN fen_index fi ON fi.line_id = l.id
WHERE fi.fen = :target_fen;

-- ------------------------------------------------
-- 今日復習すべきラインの取得
-- ------------------------------------------------
SELECT l.*, tl.note, t.name AS theme_name
FROM review_progress rp
JOIN theme_lines tl ON tl.id = rp.theme_line_id
JOIN lines l ON l.id = tl.line_id
JOIN themes t ON t.id = tl.theme_id
WHERE rp.next_review <= date('now')
ORDER BY rp.next_review ASC;

-- ------------------------------------------------
-- スキルグラフ全体の取得（nodes + edges）
-- ------------------------------------------------
-- nodes
SELECT
    sb.id, sb.name, sb.tags, sb.source_type,
    l.start_fen, l.final_fen, l.move_count,
    sm.level, sm.xp, sm.weapon_score, sm.is_signature,
    sm.last_success_at, sm.last_game_miss_at,
    sm.game_matches, sm.game_misses
FROM skill_blocks sb
JOIN lines l ON l.id = sb.line_id
LEFT JOIN skill_mastery sm ON sm.skill_block_id = sb.id;

-- edges
SELECT parent_block_id, child_block_id, link_fen, link_type
FROM skill_links;

-- ------------------------------------------------
-- 錆びたスキルブロックの取得（aging + rusty + critical）
-- ------------------------------------------------
-- rust_level は Python 側で計算するため、入力値を取得する
SELECT
    sb.id, sb.name,
    sm.last_success_at,
    sm.last_game_miss_at,
    rp.interval_days,
    rp.next_review
FROM skill_blocks sb
JOIN lines l ON l.id = sb.line_id
JOIN theme_lines tl ON tl.line_id = l.id
JOIN review_progress rp ON rp.theme_line_id = tl.id
LEFT JOIN skill_mastery sm ON sm.skill_block_id = sb.id
ORDER BY rp.next_review ASC;

-- ------------------------------------------------
-- 得意武器（Signature Weapon）の取得
-- ------------------------------------------------
SELECT
    sb.id, sb.name, sb.tags,
    sm.weapon_score, sm.is_signature, sm.signature_title,
    sm.perfect_runs, sm.game_matches, sm.level
FROM skill_blocks sb
JOIN skill_mastery sm ON sm.skill_block_id = sb.id
WHERE sm.is_signature = 1
ORDER BY sm.weapon_score DESC;

-- ------------------------------------------------
-- 実戦ゲームとスキルブロックの照合イベント取得
-- ------------------------------------------------
SELECT
    gse.event_type, gse.fen, gse.expected_move, gse.actual_move, gse.ply,
    sb.name AS skill_name
FROM game_skill_events gse
JOIN skill_blocks sb ON sb.id = gse.skill_block_id
WHERE gse.game_id = :game_id
ORDER BY gse.ply ASC;
```

### 7.4 PGNインポートフロー

PGNファイルから本アプリのデータ構造への変換は以下の手順で行う:

```
[PGNファイル]
    │
    ▼
[python-chess の PGN パーサーで読み込み]
    │
    ▼
[バリエーション（分岐）の展開]
  - メインラインとすべてのバリエーションを再帰的にたどる
  - 各分岐を独立した一本道のラインに展開する
  - 例: メインライン + 2手目の分岐 → 2つのラインが生成される
    │
    ▼
[各ラインに対して:]
  1. start_fen を決定（PGNのSetUp/FENヘッダ、または標準初期配置）
  2. python-chess で全手を再生し合法性を検証
  3. 不正な手がある場合 → 要確認フラグを付けてスキップ or エラー通知
  4. final_fen を取得
  5. UNIQUE(start_fen, moves) で重複チェック
     - 既存ラインあり → 新規テーマへの紐付けのみ追加
     - 新規ライン → lines に INSERT
  6. fen_index を生成（全 ply の FEN + next_move を一括INSERT）
  7. theme_lines に紐付けを追加
  8. import_history に記録
```

---

## 8. サブプロジェクト: `chess-llm-bridge`

### 8.1 入力ソース

以下を入力として想定する。いずれも「盤面図・棋譜表記・解説テキストが混在した画像」である。

- Chessableなど動的コンテンツのスクリーンショット (PNG)
- 書籍・教材のスキャン画像・写真 (JPG/PNG)

### 8.2 前処理

- 指定フォルダ内の複数画像の一括読み込み
- Ollamaの入力制限に合わせたリサイズ・コントラスト調整

### 8.3 AI Vision 解析: Two-Pass Extraction

1回のプロンプトで全てを出力させるのではなく、タスクを分割して推論精度を高める。

#### Pass 1: 盤面抽出 (→ FEN)

```
指示: 「画像内のチェス盤面を探し、その状態を正確なFEN文字列のみで出力せよ。
      盤面がない場合は "NONE" と出力せよ。」
```

#### Pass 2: 棋譜抽出 (→ SAN/PGN)

```
指示: 「画像内のテキストから、実際の対局で指された本譜の手順
      （Standard Algebraic Notation）のみを抽出し、スペース区切りで出力せよ。
      解説文中の分岐手順（バリエーション）は除外せよ。」
```

> **Note:** バリエーションの分離はMVP以降、アプリケーション側のPGNパーサーで
> 行う方式への移行を検討する（LLMへの判断委任を減らし安定性を上げるため）。

### 8.4 バリデーションと自己修復ループ

抽出結果を `python-chess` ライブラリのルールエンジンで検証する。

```
[Pass 1 / Pass 2 出力]
        ↓
[python-chess による検証]
  手順が有効? → ライン登録フロー（§7.4）へ
  手順が無効? (IllegalMoveError)
        ↓
  エラー情報（何手目・何の手・なぜ無効か）を付加して
  Ollamaに再抽出をリクエスト (自己リフレクション)
  ※ 最大リトライ回数はN回（設定値）
        ↓
  N回試行後も失敗 → 該当箇所を「要確認」としてユーザに通知
```

### 8.5 出力

- `chess-api` のデータモデルへの直接書き込み（§7.4 のインポートフローに合流）
- `.pgn` ファイルへのエクスポート（外部ツール連携用）
- `.fen` ファイルへのエクスポート
- クリップボードへのコピー機能

---

## 9. AIへの指示用テンプレート（プロンプト設計案）

### Pass 1 (FEN抽出)

```
あなたは熟練したチェスインストラクター兼データエンジニアです。
提供された画像からチェス盤面を探し、その状態を正確なFEN文字列のみで出力してください。
盤面が存在しない場合は "NONE" とだけ出力してください。
それ以外のテキストは一切出力不要です。
```

### Pass 2 (SAN/PGN抽出)

```
あなたは熟練したチェスインストラクター兼データエンジニアです。
提供された画像のテキストから、本譜の手順（Standard Algebraic Notation）のみを
スペース区切りで出力してください。
解説文・コメント・分岐手順（バリエーション）は除外してください。
構造化データ以外のテキストは一切出力不要です。
```

---

## 10. VRAM管理

- RX 7600 (VRAM 8GB) を最大限活かすため、4-bit量子化モデルを使用
- 推論時のVRAM消費を 6GB 以下に抑えることを目標とする

---

## 11. 反復学習アルゴリズム

### 11.1 現状

SM-2 アルゴリズムを採用・実装済み（`app/services/sm2.py`）。

`review_progress` テーブルには `ease_factor` カラムが追加済み。

| アルゴリズム | 状態                       |
| ------------ | -------------------------- |
| SM-2         | **実装済み**               |
| FSRS         | 将来的な移行候補（未実装） |

### 11.2 SM-2 の実装詳細

```python
# grade scale: 0-5
# 5 = perfect, 4 = correct with hesitation, 3 = correct with difficulty
# 2-0 = incorrect (relearn)

def apply_sm2(state: SM2State, grade: int) -> SM2State:
    if grade >= 3:
        new_interval = 1 if reps==0 else 6 if reps==1 else round(interval * ef)
        new_ef = ef + (0.1 - (5-grade) * (0.08 + (5-grade) * 0.02))
    else:
        new_interval = 1
        new_repetitions = 0
        new_ef = ef - 0.2  # floor: 1.3
```

### 11.3 実戦 miss 時の SM-2 部分減衰

実戦ゲーム解析で「致命的な錆（miss）」を検出した場合、
フルリセットではなく**部分減衰**を適用する（`app/services/sm2.py: apply_game_miss_decay`）。

```python
def apply_game_miss_decay(state: SM2State) -> SM2State:
    """実戦でのmiss時：intervalを半減、ease_factorを微減。突然の大量復習を防ぐ。"""
    return SM2State(
        interval_days=max(1, state.interval_days // 2),
        repetitions=max(0, state.repetitions - 1),
        ease_factor=max(EASE_FACTOR_MIN, state.ease_factor - 0.1),
    )
```

**影響の連鎖:**

```
game_skill_events に 'miss' イベント記録
  → skill_mastery.last_game_miss_at 更新
  → skill_mastery.game_misses += 1
  → weapon_score 再計算 → is_signature 再評価
  → 対象スキルブロックの line_id に紐づく全 theme_lines の
    review_progress に apply_game_miss_decay を適用
  → 次の復習が早まる（次回の「今日の復習」に優先的に表示）
```

### 11.4 スキーマとの関係

- `review_progress` — SM-2 の学習スケジュール管理（テーマ×ライン単位）
- `skill_mastery` — ゲーミフィケーション状態と錆計算の入力値（スキルブロック単位）
- 両者は独立しているが、実戦 miss 時に連動して更新される

---

## 12. 将来的な拡張性 (Backlog)

- **Nix による開発環境管理:** 各プロジェクトに `flake.nix` を追加し、開発に必要なツール群（Node.js, Python, uv 等）を宣言的に管理する。Arch Linux のローリングリリースによるツールバージョン変動を回避し、環境の再現性を保証する。Nix は uv/npm/Docker と競合ではなく補完関係にある（Nix = 開発環境、uv/npm = 言語パッケージ、Docker = デプロイ）。ただし ROCm / Ollama 等の GPU 関連はシステムレベルで管理し、Nix の範囲外とする
- **バリエーション分離強化:** LLMではなくPGNパーサーによるアプリ側での変化手順分離の精度向上
- **エディタ連携:** Neovim 上でのショートカットによる盤面展開（Lua / Python 連携）
- **学習支援:** Lichess / Chess.com の解析URLへの自動変換
- **統計ダッシュボード:** テーマ別・期間別の学習進捗可視化
- **エクスポート:** 学習済みラインのPGN一括エクスポート
- **マルチユーザ:** 将来的に複数学習者の進捗管理（現時点ではシングルユーザ前提）
- **FSRS移行:** SM-2からFSRSへのアルゴリズム移行（`skill_mastery` の `stability`/`difficulty` カラム追加）
- **外部ゲーム取込の自動化:** Lichess/Chess.com APIからの実戦PGN自動取得（現状は手動PGNのみ）

---

## 13. スキルブロックシステム

### 13.1 概念

テーマシステムが「学習の整理棚」（人間が意味を付けた分類）であるのに対し、
スキルブロックシステムは**局面の因果関係グラフ**（FENの連続性による自動連結）を表す。

ゲームのスキルツリーのように、学んだラインが互いに接続してグラフ構造を形成し、
ユーザーは自分だけのチェスレパートリーの「地図」を持つことができる。

### 13.2 スキルブロックの定義

一つのスキルブロック = 一つの `lines` レコード + ユーザー定義メタデータ

```
スキルブロック「フライド・リバー必殺メイト」
  line_id → lines.id (start_fen=ツーナイト局面FEN, moves="Ng5 d5 exd5 Nxd5 Nxf7")
  name: "フライド・リバー必殺メイト"
  tags: ["italian", "two-knights", "sacrifice", "trap"]
  source_type: "original"
```

### 13.3 自動連結エンジン

新規スキルブロック登録時、`fen_index` テーブルを活用して自動的にグラフ連結を行う：

```
register_skill_block(name, line_id):
    1. block = INSERT INTO skill_blocks

    # FEN正規化（4フィールド：局面・手番・キャスリング・アンパッサン）
    # half-move clock と full-move number は無視

    # 親ブロックの探索：「自分の start_fen」で終わる既存ブロック
    2. parents = SELECT sb FROM skill_blocks sb
                 JOIN lines l ON sb.line_id = l.id
                 WHERE normalize_fen(l.final_fen) = normalize_fen(line.start_fen)
    3. INSERT INTO skill_links (parent, block, link_fen, 'auto') for each parent

    # 子ブロックの探索：「自分の final_fen」で始まる既存ブロック
    4. children = SELECT sb FROM skill_blocks sb
                  JOIN lines l ON sb.line_id = l.id
                  WHERE normalize_fen(l.start_fen) = normalize_fen(line.final_fen)
    5. INSERT INTO skill_links (block, child, link_fen, 'auto') for each child
```

### 13.4 FEN正規化

FENは6フィールド構成（局面・手番・キャスリング・アンパッサン・half-move clock・full-move number）だが、
「同じ局面」の照合には最初の4フィールドのみを使用する。

```python
def normalize_fen(fen: str) -> str:
    """FENの最初の4フィールドのみを返す（half-move clock と full-move number を除く）。"""
    parts = fen.split()
    return " ".join(parts[:4])
```

### 13.5 錆（Rust）システム

習得済みのスキルが時間経過や不使用により「錆びる」概念を実装する。

**錆レベルの4段階:**

| レベル     | 判定条件                                              | 意味                     |
| ---------- | ----------------------------------------------------- | ------------------------ |
| `fresh`    | 最終成功から `interval_days` 以内                     | 定着中・現役             |
| `aging`    | 最終成功から `interval_days × 1.5` 超過               | やや危ない               |
| `rusty`    | 最終成功から `interval_days × 3.0` 超過、または未練習 | 要復習                   |
| `critical` | `last_game_miss_at > last_success_at`                 | 実戦でのど忘れ（最優先） |

**3つの錆信号:**

1. **時間減衰（エビングハウス忘却曲線ベース）:** `last_success_at` と `interval_days` の比率
2. **実戦証拠:** `game_skill_events` の match/miss イベント
3. **復習の質:** SM-2 の `ease_factor`（低いほど「覚えにくい」）

### 13.6 得意武器（Signature Weapon）

頻繁に学習し、実戦でも成功率が高いスキルブロックを「得意武器」として昇華させる。

**weapon_score の計算:**

```python
import math

def compute_weapon_score(
    perfect_runs: int,
    game_matches: int,
    game_misses: int,
    days_since_success: int,
) -> float:
    # 学習深度（対数スケール、grinding防止）
    # 実戦マッチは2倍の重みを持つ
    depth = math.log(1 + perfect_runs + game_matches * 2)

    # 実戦成功率（データなし時は 0.5 とする）
    total = game_matches + game_misses
    game_rate = game_matches / total if total > 0 else 0.5

    # 時間減衰（半減期 ≈ 30日）
    decay = math.exp(-0.023 * days_since_success)

    return depth * (0.4 + 0.6 * game_rate) * decay
```

`weapon_score >= 3.0`（初期閾値、設定で変更可）のスキルブロックを `is_signature = 1` に設定。
得意武器にはユーザー自身が「二つ名」（`signature_title`）を設定できる。LLMは使用しない。

### 13.7 スキルブロック共有

スキルブロックをエンコードした「共有コード」を生成・取込できる。

**エンコード形式:**

```json
// 共有コードのペイロード（JSON）
{
  "v": 1,
  "name": "必殺フライド・リバー・トラップ",
  "start_fen": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
  "moves": "Ng5 d5 exd5 Nxd5 Nxf7",
  "tags": ["italian", "sacrifice", "trap"],
  "desc": "ツーナイト・ディフェンスからの即死トラップ"
}
```

↓ JSON → zlib 圧縮 → Base64 エンコード → プレフィックス付与

```
chessmadness:AeJyrVspIzcnJV7JSUMov...（短い文字列）
```

**エンドポイント:**

| Method | Path                     | 説明                                            |
| ------ | ------------------------ | ----------------------------------------------- |
| `POST` | `/skills/share`          | 共有コード生成                                  |
| `POST` | `/skills/import-code`    | 共有コードから取込（python-chess で全手を検証） |
| `GET`  | `/skills/preview/{code}` | 取込前のプレビュー（デコードのみ、DB変更なし）  |

**セキュリティ:** `import-code` では必ず `build_fen_index` による全手の合法性検証を行う。

### 13.8 フォーク機能

他者から取り込んだスキルブロック、または自分の既存スキルブロックを末端から延長して
新たな派生スキルを作成できる。

```
POST /skills/{block_id}/fork
body: { "additional_moves": "Nc3 Qf6", "name": "俺流対策" }

処理:
  1. 元ブロックの final_fen を取得
  2. additional_moves を python-chess で検証
  3. 新しい line を register（start_fen = 元の final_fen, moves = additional_moves）
  4. 新しい skill_block を作成（forked_from_id = 元のblock_id, source_type = 'forked'）
  5. skill_links で 元ブロック → フォークブロック を接続（link_type = 'manual'）
```

### 13.9 スキルシステムの全エンドポイント一覧

| Method   | Path                        | 説明                                                  |
| -------- | --------------------------- | ----------------------------------------------------- |
| `POST`   | `/skills`                   | スキルブロック作成（自動連結実行）                    |
| `GET`    | `/skills/tree`              | 全スキルグラフ取得（nodes + edges）                   |
| `GET`    | `/skills/{id}`              | ブロック詳細（mastery + rust_level 含む）             |
| `PATCH`  | `/skills/{id}`              | 名前/タグ/説明/二つ名の編集                           |
| `DELETE` | `/skills/{id}`              | スキルブロック削除                                    |
| `GET`    | `/skills/{id}/children`     | 子スキル一覧                                          |
| `GET`    | `/skills/{id}/ancestors`    | ルートまでのパス                                      |
| `GET`    | `/skills/rusty`             | 錆びたスキル一覧（rust_level = aging/rusty/critical） |
| `GET`    | `/skills/critical`          | 実戦 miss ありのスキル一覧                            |
| `GET`    | `/skills/signatures`        | 得意武器一覧                                          |
| `GET`    | `/skills/search`            | FEN / 名前 / タグでスキル検索                         |
| `GET`    | `/skills/mastery/dashboard` | 全体サマリー（レベル分布・錆の状態・得意武器）        |
| `POST`   | `/skills/share`             | 共有コード生成                                        |
| `POST`   | `/skills/import-code`       | 共有コードから取込                                    |
| `GET`    | `/skills/preview/{code}`    | 共有コードプレビュー                                  |
| `POST`   | `/skills/{id}/fork`         | フォーク作成                                          |
| `POST`   | `/games/analyze`            | 手動 PGN を解析してスキルブロックと照合               |
| `GET`    | `/games`                    | 解析済みゲーム一覧                                    |
| `GET`    | `/games/{id}/events`        | ゲームの match/miss イベント一覧                      |
