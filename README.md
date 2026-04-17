# StocktoNotion

อัปเดตช่อง **"ราคาปัจจุบัน (ต่อหน่วย)"** ใน Notion database `📒 ประวัติการซื้อขายทั้งหมด` โดยอัตโนมัติ ด้วย GitHub Actions

## วิธีทำงาน

สคริปต์ `update_prices.py` จะ:

1. ดึงทุกแถวของ database ผ่าน Notion API
2. อ่าน `ชื่อ / Ticker`, `ตลาด`, `ประเภทสินทรัพย์` เพื่อเลือกแหล่งราคา
3. ดึงราคาปัจจุบันจาก:
   - **หุ้น/ETF สหรัฐฯ** (NASDAQ / NYSE / NYSE Arca) → `yfinance`
   - **หุ้น SET** → `yfinance` ต่อท้าย `.BK` (เช่น `SCB.BK`)
   - **กองทุนรวมไทย** → `pythainav` (ดึง NAV ล่าสุดจาก Finnomena/WealthMagik)
4. เขียนราคากลับไปที่ช่อง `ราคาปัจจุบัน (ต่อหน่วย)`
5. Formula `กำไร/ขาดทุน`, `กำไร/ขาดทุน (%)`, `มูลค่าปัจจุบัน` ใน Notion จะคำนวณให้เองอัตโนมัติ

GitHub Actions ตั้งเวลารันทุก **30 นาที** ในเวลาทำการ:
- SET: 10:00–16:30 ICT (03:00–09:30 UTC) จันทร์–ศุกร์
- US : 09:30–16:00 ET  (13:30–21:00 UTC) จันทร์–ศุกร์

## การติดตั้ง (ทำครั้งเดียว)

### 1) สร้าง Notion Integration

1. ไปที่ https://www.notion.so/my-integrations → **New integration**
2. ตั้งชื่อ เช่น `StocktoNotion`, เลือก workspace, Type = **Internal**
3. คัดลอก **Internal Integration Secret** (ขึ้นต้น `secret_` หรือ `ntn_`)
4. เปิดหน้า `📒 ประวัติการซื้อขายทั้งหมด` ใน Notion → คลิก `•••` มุมขวาบน → **Connections** → เพิ่ม integration ที่สร้างไว้

### 2) สร้าง GitHub repository

```bash
cd StocktoNotion
git init
git add .
git commit -m "Initial commit: Notion portfolio auto price updater"
git branch -M main
# สร้าง repo เปล่าใน GitHub ก่อน แล้วค่อยเชื่อม remote
git remote add origin git@github.com:<your-username>/StocktoNotion.git
git push -u origin main
```

### 3) ตั้งค่า GitHub Secrets

ใน repo ของคุณ → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

เพิ่ม 2 ตัว:

| Name                 | Value                                                 |
| -------------------- | ----------------------------------------------------- |
| `NOTION_TOKEN`       | Internal Integration Secret จากขั้นตอน 1            |
| `NOTION_DATABASE_ID` | `f9849d70baef41c1a4897e7cf1fb75dc`                    |

> วิธีหา database ID: เปิด database ใน browser แล้วดู URL → `notion.so/<workspace>/<DATABASE_ID>?v=...` เอาเฉพาะส่วน 32 ตัวอักษรก่อน `?v=`

### 4) ทดสอบ

- ไปที่แท็บ **Actions** ใน GitHub
- เลือก **Update Notion Portfolio Prices** → **Run workflow** → **Run workflow**
- ดู log ว่าอัปเดตกี่รายการสำเร็จ

หลังจากนั้น workflow จะรันอัตโนมัติทุก 30 นาทีในเวลาทำการ

## ทดสอบแบบ local (ก่อน push)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# แก้ .env ใส่ NOTION_TOKEN ของจริง

set -a; source .env; set +a
python update_prices.py
```

## การปรับแต่ง

- **เปลี่ยนช่วงเวลาอัปเดต** → แก้ `.github/workflows/update_prices.yml` ตรง `cron`
- **รันทุกชั่วโมงแทน 30 นาที** → เปลี่ยน `*/30` เป็น `0`
- **เพิ่ม market / broker** → เพิ่ม branch ใน `fetch_price()` ใน `update_prices.py`

## ข้อจำกัด / ข้อควรระวัง

- **GitHub Actions cron** อาจล่าช้าได้หลายนาทีในช่วง peak ของ GitHub (ไม่ใช่ realtime ระดับวินาที)
- **yfinance** ใช้ข้อมูลจาก Yahoo Finance ซึ่งมี **delay ~15 นาทีสำหรับ SET** (US markets realtime หรือ near-realtime)
- **Thai mutual funds** NAV ประกาศวันละครั้งหลังตลาดปิด (ประมาณ 20:00–22:00 ICT) — การรันทุก 30 นาทีแค่ช่วยจับ NAV ใหม่เร็วขึ้น
- ถ้า `pythainav` ดึงไม่ได้ (เว็บต้นทางเปลี่ยน) สามารถสลับไปใช้ WealthMagik scrape โดยตรงได้ — แจ้งผมถ้าต้องการเพิ่ม fallback

## โครงสร้างไฟล์

```
StocktoNotion/
├── .github/workflows/update_prices.yml   # ตัวสั่งให้ GitHub Actions รัน
├── update_prices.py                      # สคริปต์อัปเดตราคา
├── requirements.txt                      # Python dependencies
├── .gitignore
├── .env.example                          # สำหรับทดสอบ local
└── README.md
```

## License

ใช้งานส่วนตัว
