# プロジェクト仕様書: Chess Repertoire Trainer (仮)

最終更新: 2026/02/25

---

## 1. プロジェクト概要

### 1.1 目的

チェスの反復学習（Spaced Repetition）に特化したローカル完結型アプリケーション。

書籍・教材コンテンツ（スクリーンショット・スキャン画像・PGNファイル）から棋譜を取り込み、
独自のデータ構造で管理し、反復練習を通じてレパートリーを定着させることを主眼とする。

本プロジェクトは **Scid や ChessX の単なる代替ではない**。
既存のデータベースソフトウェアが「対局データの蓄積と検索」を目的とするのに対し、
本プロジェクトは **「手筋（ライン）の記憶定着」** を目的とする学習アプリケーションである。

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

- **個人利用の徹底:** 抽出データは個人学習目的に限定し、第三者への配布・共有機能は設けない
- **事実の抽出:** 書籍・教材の創作物（解説文・図版デザイン・UI要素）ではなく、
  客観的事実（棋譜・駒の配置）の抽出のみを目的とする
- チェスの棋譜は著作権法上「事実の記録」であり創作物ではないとされるが、
  解説文やレイアウトは創作物であるため、これらの抽出・保存は行わない

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
│  ├───────────────────────────────────────────┤  │
│  │ python-chess                              │  │
│  │  - PGN/FEN パース・バリデーション           │  │
│  │  - fen_index 生成（全中間局面展開）         │  │
│  │  - インポート時の分岐展開                   │  │
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

### 7.2 SQLite スキーマ

```sql
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

CREATE TABLE review_progress (
    id              INTEGER PRIMARY KEY,
    theme_line_id   INTEGER NOT NULL REFERENCES theme_lines(id) ON DELETE CASCADE,
    interval_days   INTEGER NOT NULL DEFAULT 0,
    repetitions     INTEGER NOT NULL DEFAULT 0,
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

アルゴリズムは未確定。以下の候補を検討中:

| アルゴリズム | 概要                                                                            | 備考                   |
| ------------ | ------------------------------------------------------------------------------- | ---------------------- |
| SM-2         | Ankiが採用する間隔反復アルゴリズム。ease_factor / interval / repetitions で管理 | 実績豊富、実装シンプル |
| FSRS         | Ankiの新アルゴリズム。SM-2より精度が高いとされる                                | 実装がやや複雑         |

### 11.2 スキーマとの関係

`review_progress` テーブルは現時点では汎用的なカラム（interval_days, repetitions, next_review, last_reviewed）のみ定義している。
アルゴリズム確定後に `ease_factor`（SM-2）や `stability` / `difficulty`（FSRS）等のアルゴリズム固有カラムを追加する。

---

## 12. 将来的な拡張性 (Backlog)

- **Nix による開発環境管理:** 各プロジェクトに `flake.nix` を追加し、開発に必要なツール群（Node.js, Python, uv 等）を宣言的に管理する。Arch Linux のローリングリリースによるツールバージョン変動を回避し、環境の再現性を保証する。Nix は uv/npm/Docker と競合ではなく補完関係にある（Nix = 開発環境、uv/npm = 言語パッケージ、Docker = デプロイ）。ただし ROCm / Ollama 等の GPU 関連はシステムレベルで管理し、Nix の範囲外とする
- **バリエーション分離強化:** LLMではなくPGNパーサーによるアプリ側での変化手順分離の精度向上
- **エディタ連携:** Neovim 上でのショートカットによる盤面展開（Lua / Python 連携）
- **学習支援:** Lichess / Chess.com の解析URLへの自動変換
- **統計ダッシュボード:** テーマ別・期間別の学習進捗可視化
- **エクスポート:** 学習済みラインのPGN一括エクスポート
- **マルチユーザ:** 将来的に複数学習者の進捗管理（現時点ではシングルユーザ前提）
