# 台股每日晨報排程（twstock + Notion MCP）

最後更新時間: 2026-08-31

## 需求與建立過程

使用者要求：「排程每日5點提供股市統整報告 通過來源 https://github.com/mlouielu/twstock」。

- **報告範圍**：大盤指數 + 三大法人買賣超 + 熱門股
- **報告去向**：寫入 Notion（透過本機 Notion MCP `notion-mcp-server`）
- **Repo 來源**：直接 `pip install twstock`（已發布 PyPI）

---

## ~~舊排程（Claude Code cloud routine）~~ ⚠️ 已失效

> **狀態：已失效（2026-08-31 確認）**
> 此排程建立於 Claude Code 雲端 routines 系統（`claude.ai/code/routines`），
> 與現行 Antigravity (AGY) 環境不同，排程已無法執行。

- **Trigger ID**: `trig_016ewc9HiSPES6GKT25s4JyC`（已失效）
- **連結**: https://claude.ai/code/routines/trig_016ewc9HiSPES6GKT25s4JyC

---

## 現行排程（AGY 本機 cron）

- **建立時間**: 2026-08-31
- **Task ID**: `28ccc66e-fdd3-4c6c-9f95-15a85ee93f79/task-110`
- **觸發時間**: `0 21 * * *`（UTC）= 台北時間每日 **05:00**
- **寫入模式**: **複寫**固定 Notion 頁面（清除舊內容後重寫，標題更新含當日日期）
- **環境**: Antigravity (AGY) 本機排程，搭配本機 Notion MCP（`notion-mcp-server`）
- **Notion Bot**: `gemini`（ID: `3cdd1702-291b-8172-9db4-0027cd5030f6`）
- **Notion 目標頁面 page_id**: 待補（需先授權 gemini integration）

### 追蹤個股清單

| 代號 | 名稱 | 追蹤項目 |
|------|------|---------|
| 3037 | 欣興電子 | 收盤價、漲跌幅、成交量、三大法人買賣超 |

### 排程 Prompt 內容

```
執行台股每日晨報（twstock），並複寫 Notion 固定頁面：

今天日期請用 Python datetime 取得（台北時區 UTC+8）。

步驟：
1. 執行 `pip install twstock requests --quiet`
2. 用 twstock 撈台股資料（若當日無資料則用最近交易日）；必要時用 WebFetch 補齊
   openapi.twse.com.tw 資料，涵蓋：
   - TAIEX 大盤指數與漲跌幅
   - 三大法人（外資/投信/自營商）買賣超金額
   - 成交量前 10 大熱門股
   - 漲跌幅前 5 名排行
3. 額外追蹤個股（每日必須包含）：
   - 欣興電子（3037）：當日收盤價、漲跌幅、成交量、三大法人買賣超
4. 整理成繁體中文台股每日晨報，報告結構：
   - 標題：台股每日晨報（YYYY-MM-DD）
   - 大盤摘要
   - 三大法人動向
   - 熱門股排行
   - 個股追蹤：欣興電子（3037）
5. 用 Notion MCP 操作固定頁面（page_id 見文件）：
   a. 先清除該頁面所有現有 block
   b. 將完整報告內容以 blocks 寫入
   c. 更新頁面標題為「台股每日晨報 YYYY-MM-DD」
6. 最終回覆包含完整報告全文
```

### TODO

- [ ] 在 Notion 建立「台股每日晨報」頁面並授權 gemini integration 存取
- [ ] 取得該頁面 page_id，填入文件與排程 prompt

