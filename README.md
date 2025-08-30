# AIWolf 対戦分析パイプライン

このパイプラインは AIWolf（人狼知能コンテスト）のゲームログを処理し、分析に適した対戦セットを最適に選択するためのツール群です。

## 概要

パイプラインは次の3つのスクリプトから構成され、順番に実行します。

1. **fetch\_aiwolf\_logs.py** - AIWolf サーバからゲームログを取得
2. **pattern\_of\_matches\_generator.py** - ログを解析して役職パターンを生成
3. **match\_selection\_optimizer.py** - 整数計画法（ILP）で最適な対戦集合を選択

## 事前準備

以下の依存ライブラリをインストールしてください。

```bash
pip install numpy pandas pulp ortools openpyxl
```

## 使用方法

### ステップ1: ゲームログの取得

AIWolf サーバからログをダウンロードしてローカルに保存します。

```bash
python scripts/fetch_aiwolf_logs.py
```

**処理内容:**

* AIWolf サーバに接続して対戦ログを取得
* ログを `checker/data/raw/{dataset_name}/` に整理
* 各対戦は `game1`, `game2` などのファイルとして保存

**出力:**

* `checker/data/raw/{dataset_name}/` 以下に生ログファイル

---

### ステップ2: 対戦パターンの生成

取得したログを解析し、役職割り当てパターンを抽出します。

```bash
python scripts/pattern_of_matches_generator.py
```

**処理内容:**

* `checker/data/raw/` からログを読み込み
* 各対戦の役職割り当てを抽出
* チームと役職の対応マップを作成
* 役職分布の統計を生成

**出力:**

* `checker/data/pattern_of_matches/{dataset_name}/pattern_of_matches.json`

  * `idx_team_map`: チーム番号とチーム名の対応表
  * `role_num_map`: ゲーム設定ごとの役職数
  * `pattern_of_matches`: 各対戦における役職割り当てリスト

---

### ステップ3: 対戦集合の最適化

整数線形計画法（ILP）を用いて、分析に適した対戦集合を選択します。

```bash
python scripts/match_selection_optimizer.py
```

**対話式プロンプト:**

1. 利用可能なパターンファイルから選択
2. 選択する試合数（Enterでデフォルト）
3. チームごとの「0回役職」の上限（0=禁止, 1=1つまで許可, …）
4. 「0回役職」の数え方（元データで出現した役職だけ\[Y] / 全役職\[n]）
5. 各チームが最低1回は登場するかどうか \[Y/n]

**処理内容:**

* ILP による最適化

  * チームの出場回数のバランス
  * 各役職の割り当てバランス
  * チーム×役職のカバレッジ
* 制約条件

  * 試合数を指定数に固定
  * 「0回役職」の上限制御
  * （オプション）各チーム最低1回は登場

**出力:**

* 選ばれた試合ファイルが `checker/data/selected_files/{dataset_name}/` にコピー
* 統計表が `checker/table/{dataset_name}/` に保存

  * `role_distribution_{dataset_name}.csv` — チームごとの役職数
  * `optimization_summary_{dataset_name}.csv` — 最適化の指標
  * `selected_matches_{dataset_name}.csv` — 選択された試合リスト

---

## ディレクトリ構造

```
checker/
├── scripts/
│   ├── fetch_aiwolf_logs.py
│   ├── pattern_of_matches_generator.py
│   └── match_selection_optimizer.py
├── data/
│   ├── raw/                    # 取得した生ログ
│   │   └── {dataset_name}/
│   │       ├── game1
│   │       ├── game2
│   │       └── ...
│   ├── pattern_of_matches/     # 解析後のパターン
│   │   └── {dataset_name}/
│   │       └── pattern_of_matches.json
│   └── selected_files/         # 最適化で選ばれた試合
│       └── {dataset_name}/
│           ├── game1
│           ├── game5
│           └── ...
└── table/                       # 分析結果
    └── {dataset_name}/
        ├── role_distribution_{dataset_name}.csv
        ├── optimization_summary_{dataset_name}.csv
        └── selected_matches_{dataset_name}.csv
```

---

## 役職の種類

本システムが扱う AIWolf の役職は以下です。

* **村人陣営:** VILLAGER, SEER, BODYGUARD, MEDIUM
* **人狼陣営:** WEREWOLF, POSSESSED

---

## 最適化の詳細

ILP の目的は以下を最小化することです。

* チーム総出場回数のばらつき
* 役職ごとの割り当て回数のばらつき
* （役職重要度に応じた重み付け可）

制約条件:

* 選択する試合数を固定
* 各チームの役職カバレッジ（0回役職の上限制御）
* （オプション）各チームが最低1回は登場

---
