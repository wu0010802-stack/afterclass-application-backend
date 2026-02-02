# 常春藤報名表後端系統 (PostgreSQL 正規化版)

這是一個使用 PostgreSQL 資料庫的報名表後端系統，採用正規化設計。

## 系統需求

- PostgreSQL (已安裝)
- Python 3 (已安裝)
- pg8000 (Python Driver, 已安裝)

## 資料庫架構

### 資料庫名稱：`afterschool`

### 資料表結構（正規化設計）：

1. **students** - 學生資料表
   - id (主鍵)
   - name (學生姓名，唯一)
   - created_at (建立時間)

2. **courses** - 課程資料表
   - id (主鍵)
   - name (課程名稱，唯一)
   - price (價格)
   - sessions (堂數)
   - frequency (上課頻率)
   - description (說明)

3. **supplies** - 用品資料表
   - id (主鍵)
   - name (用品名稱，唯一)
   - price (價格)

4. **registrations** - 報名主表
   - id (主鍵)
   - student_id (外鍵 → students.id)
   - class_name (班級)
   - created_at (建立時間)
   - updated_at (更新時間)

5. **registration_courses** - 報名課程關聯表（多對多）
   - id (主鍵)
   - registration_id (外鍵 → registrations.id)
   - course_id (外鍵 → courses.id)

6. **registration_supplies** - 報名用品關聯表（多對多）
   - id (主鍵)
   - registration_id (外鍵 → registrations.id)
   - supply_id (外鍵 → supplies.id)

## 如何啟動

1. 確保您的 PostgreSQL 服務正在執行。
2. 在此資料夾打開終端機。
3. 執行以下指令：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. 執行以下指令啟動後端服務：

```bash
python3 app.py
```

看到 `Python (PostgreSQL) Server running at http://localhost:3000/` 即表示啟動成功。

## 使用 Postbird 查看資料

1. 開啟 Postbird
2. 連線設定：
   - Host: localhost
   - Port: 5432
   - User: yilunwu
   - Database: **afterschool**
3. 連線後即可查看所有資料表

## 正規化優點

- 避免資料重複
- 易於維護和更新
- 支援複雜查詢
- 資料一致性更好
