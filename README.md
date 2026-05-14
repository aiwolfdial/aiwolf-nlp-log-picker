# AIWolf 対戦ログ ピッカー

AIWolf（人狼知能コンテスト）の対戦ログをトラック別フォルダから直接読み込み、
整数線形計画法（ILP）で分析用に偏りの少ない対戦集合を選び出すツールです。

## ディレクトリ構造

```
aiwolf-nlp-log-picker/
├── scripts/
│   └── pick_matches.py          # 唯一のメインスクリプト
├── data/
│   └── {track_name}/            # トラック別フォルダを自分で作成
│       ├── game1.log
│       ├── game2.log
│       └── ...
├── selected/                    # 選ばれたログのコピー（自動生成）
│   └── {track_name}/
│       ├── game5.log
│       └── ...
└── table/                       # 統計テーブル（自動生成）
    └── {track_name}/
        ├── role_distribution_{track_name}.csv
        ├── optimization_summary_{track_name}.csv
        └── selected_matches_{track_name}.csv
```

## 事前準備

```bash
pip install numpy pandas pulp openpyxl
```

## 使い方

### 1. ログを配置

トラックごとに `data/{track_name}/` を作り、`.log` ファイルを直接置きます。

```
data/inlg2025_truck5/game1.log
data/inlg2025_truck5/game2.log
...
```

各ログは AIWolf 標準の CSV 形式で、最初の数行に `status` 行（役職割当）が並んでいる必要があります（5人戦は先頭5行、13人戦は先頭13行を解析）。

### 2. ピッカーを実行

```bash
python scripts/pick_matches.py
```

対話プロンプトで以下を指定します。

1. トラックを選択（`data/` 配下のフォルダから自動検出）
2. 選択する試合数（Enter でデフォルト = 全体の半分）
3. チームごとの「0回役職」許容数（0=禁止、1=1つまで、…）
4. 「0回役職」の数え方（元データに登場した役職だけ [Y] / 全役職 [n]）
5. 各チームが最低1回は登場するか [Y/n]

プレイヤー人数と役職構成は各ログの冒頭 `status` 行から自動検出されます（5人戦・13人戦に限らず任意の構成に対応）。

### 3. 結果を確認

- `selected/{track_name}/*.log` … 選ばれた対戦ログのコピー
- `table/{track_name}/role_distribution_{track_name}.csv` … チーム×役職の出現数
- `table/{track_name}/optimization_summary_{track_name}.csv` … 最適化サマリ
- `table/{track_name}/selected_matches_{track_name}.csv` … 選択された試合一覧

## 役職

- **村人陣営:** VILLAGER, SEER, BODYGUARD, MEDIUM
- **人狼陣営:** WEREWOLF, POSSESSED

各役職の出現数（`role_num_map`）はログから自動検出され、ILP の重み付けに使われます。
よくある人数別の役職構成の例:

| 人数 | VILLAGER | SEER | BODYGUARD | MEDIUM | WEREWOLF | POSSESSED |
|------|---------:|-----:|----------:|-------:|---------:|----------:|
| 5    | 2        | 1    | 0         | 0      | 1        | 1         |
| 13   | 6        | 1    | 1         | 1      | 3        | 1         |

## 最適化の概要

ILP の目的関数は以下を最小化します（役職重みつき）。

- チームごとの総出場回数の最大値−最小値
- 役職ごとの担当回数の最大値−最小値

制約条件:

- 選ぶ試合数を固定
- 各チームの「0回役職」数の上限を制御
- （オプション）各チームが最低1回は登場
