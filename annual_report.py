# -*- coding: utf-8 -*-
"""
年度观影报告生成器
Annual Playback Report Generator

设计哲学：
这不是一份统计报表，
而是一段被系统温柔整理过的记忆。

GitHub: https://github.com/zzstar101/jellyfin-playback-report
"""

import sqlite3
import requests
import os
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from collections import defaultdict

# =========================
# 🔧 配置区（请修改为你的配置）
# =========================

# 报告年份
REPORT_YEAR = 2025

# 数据库路径
DB_PATH = "./cache/playback_reporting.db"

# Jellyfin 服务器
JELLYFIN_URL = "https://your-jellyfin-server.com"
JELLYFIN_API_KEY = "YOUR_JELLYFIN_API_KEY"

# 站点名称
SITE_NAME = "YOUR_SITE_NAME"

# 输出目录
OUTPUT_DIR = "./posters"

# 字体路径（请根据系统修改）
# Windows: "C:/Windows/Fonts/msyh.ttc"
# Linux: "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
FONT_DIR = "C:/Windows/Fonts/"

# =========================
# 数据查询函数
# =========================

def query(sql, params=()):
    """执行 SQL 查询"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def sec_to_hm(sec: int) -> str:
    """秒数转 Xh Xm 格式"""
    if sec < 60:
        return "< 1m"
    h, r = divmod(sec, 3600)
    m = r // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"

def extract_name(item_name: str) -> str:
    """从 Episode 名称提取剧名"""
    if " - " in item_name:
        return item_name.split(" - ")[0].strip()
    return item_name.strip()

# =========================
# Jellyfin API
# =========================

def search_jellyfin_item(name, item_type="Series"):
    """搜索 Jellyfin 媒体项"""
    try:
        url = f"{JELLYFIN_URL}/Items"
        params = {
            "searchTerm": name,
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "Limit": 1
        }
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("Items", [])
            if items:
                return items[0].get("Id")
    except:
        pass
    return None

def get_poster(item_id):
    """获取封面图片"""
    if not item_id:
        return None
    url = f"{JELLYFIN_URL}/Items/{item_id}/Images/Primary"
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return Image.open(BytesIO(r.content))
    except:
        pass
    return None

# =========================
# 数据统计
# =========================

def get_annual_data(year):
    """获取年度播放数据（不区分内容类别）"""
    print(f"\n📊 正在统计 {year} 年播放数据...")
    print("   注：不区分电影/电视剧/番剧，统一按播放时长排序")
    
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31 23:59:59"
    
    # 获取实际统计周期
    date_range_row = query("""
        SELECT MIN(DateCreated) AS FirstDate, MAX(DateCreated) AS LastDate
        FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
    """, (start_date, end_date))
    
    actual_start = date_range_row[0]["FirstDate"][:10] if date_range_row and date_range_row[0]["FirstDate"] else start_date[:10]
    actual_end = date_range_row[0]["LastDate"][:10] if date_range_row and date_range_row[0]["LastDate"] else end_date[:10]
    
    stats_period = f"{actual_start} 至 {actual_end}"
    
    # 每月 Top 3
    monthly_top3 = {}
    
    for month in range(1, 13):
        month_start = f"{year}-{month:02d}-01"
        if month == 12:
            month_end = f"{year}-12-31 23:59:59"
        else:
            month_end = f"{year}-{month+1:02d}-01"
        
        rows = query("""
            SELECT
                CASE 
                    WHEN ItemType = 'Episode' THEN 
                        SUBSTR(ItemName, 1, INSTR(ItemName || ' - ', ' - ') - 1)
                    ELSE ItemName 
                END AS ShowName,
                ItemType,
                SUM(PlayDuration) AS TotalDuration,
                COUNT(*) AS PlayCount
            FROM PlaybackActivity
            WHERE DateCreated >= ? AND DateCreated < ?
            GROUP BY ShowName
            ORDER BY TotalDuration DESC
            LIMIT 3
        """, (month_start, month_end))
        
        month_data = []
        for row in rows:
            name = row["ShowName"] or "未知"
            item_type = row["ItemType"]
            duration = row["TotalDuration"] or 0
            
            if item_type == "Movie":
                item_id = search_jellyfin_item(name, "Movie")
            else:
                item_id = search_jellyfin_item(name, "Series")
            
            poster = get_poster(item_id)
            
            if poster:
                month_data.append({
                    "name": name,
                    "duration": duration,
                    "poster": poster
                })
        
        monthly_top3[month] = month_data
        
        if month_data:
            print(f"  {month:2d}月: {len(month_data)} 条记录")
        else:
            print(f"  {month:2d}月: 暂无播放记录")
    
    # 年度总结
    print("\n📈 统计年度总结...")
    
    total_duration_row = query("""
        SELECT SUM(PlayDuration) AS Total FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
    """, (start_date, end_date))
    total_duration = total_duration_row[0]["Total"] or 0
    
    total_items_row = query("""
        SELECT COUNT(DISTINCT 
            CASE 
                WHEN ItemType = 'Episode' THEN 
                    SUBSTR(ItemName, 1, INSTR(ItemName || ' - ', ' - ') - 1)
                ELSE ItemName 
            END
        ) AS Total FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
    """, (start_date, end_date))
    total_items = total_items_row[0]["Total"] or 0
    
    top_show_row = query("""
        SELECT
            CASE 
                WHEN ItemType = 'Episode' THEN 
                    SUBSTR(ItemName, 1, INSTR(ItemName || ' - ', ' - ') - 1)
                ELSE ItemName 
            END AS ShowName,
            SUM(PlayDuration) AS TotalDuration
        FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
        GROUP BY ShowName
        ORDER BY TotalDuration DESC
        LIMIT 1
    """, (start_date, end_date))
    
    top_show = None
    if top_show_row:
        top_show = {
            "name": top_show_row[0]["ShowName"],
            "duration": top_show_row[0]["TotalDuration"]
        }
    
    top_client_row = query("""
        SELECT ClientName, COUNT(*) AS Cnt
        FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
        GROUP BY ClientName
        ORDER BY Cnt DESC
        LIMIT 1
    """, (start_date, end_date))
    
    top_client = None
    if top_client_row:
        top_client = {
            "name": top_client_row[0]["ClientName"] or "未知",
            "count": top_client_row[0]["Cnt"]
        }
    
    top_user_row = query("""
        SELECT UserId, SUM(PlayDuration) AS TotalDuration
        FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
        GROUP BY UserId
        ORDER BY TotalDuration DESC
        LIMIT 1
    """, (start_date, end_date))
    
    top_user = None
    if top_user_row and top_user_row[0]["UserId"]:
        user_id = top_user_row[0]["UserId"]
        user_duration = top_user_row[0]["TotalDuration"]
        
        try:
            url = f"{JELLYFIN_URL}/Users/{user_id}"
            headers = {"X-Emby-Token": JELLYFIN_API_KEY}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                user_name = r.json().get("Name", "未知用户")
            else:
                user_name = "未知用户"
        except:
            user_name = "未知用户"
        
        top_user = {
            "name": user_name,
            "duration": user_duration
        }
    
    annual_summary = {
        "stats_period": stats_period,
        "total_duration": total_duration,
        "total_items": total_items,
        "top_show": top_show,
        "top_user": top_user,
        "top_client": top_client
    }
    
    # 补充数据
    print("\n📋 统计补充数据...")
    extra_facts = []
    
    night_rows = query("""
        SELECT 
            SUM(CASE WHEN CAST(strftime('%H', DateCreated) AS INTEGER) >= 22 
                     OR CAST(strftime('%H', DateCreated) AS INTEGER) < 4 
                THEN PlayDuration ELSE 0 END) AS NightDuration,
            SUM(PlayDuration) AS TotalDuration
        FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
    """, (start_date, end_date))
    
    if night_rows and night_rows[0]["TotalDuration"]:
        night_dur = night_rows[0]["NightDuration"] or 0
        total_dur = night_rows[0]["TotalDuration"]
        night_percent = int(night_dur / total_dur * 100)
        if night_percent > 0:
            extra_facts.append(f"22:00–04:00 时段播放占比：{night_percent}%")
    
    max_day_row = query("""
        SELECT DATE(DateCreated) AS Day, SUM(PlayDuration) AS DayTotal
        FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
        GROUP BY DATE(DateCreated)
        ORDER BY DayTotal DESC
        LIMIT 1
    """, (start_date, end_date))
    
    if max_day_row and max_day_row[0]["DayTotal"]:
        max_day = max_day_row[0]["Day"]
        max_day_dur = max_day_row[0]["DayTotal"]
        extra_facts.append(f"单日最长播放记录：{max_day}（{sec_to_hm(max_day_dur)}）")
    
    total_records_row = query("""
        SELECT COUNT(*) AS Total FROM PlaybackActivity
        WHERE DateCreated >= ? AND DateCreated <= ?
    """, (start_date, end_date))
    
    if total_records_row:
        total_records = total_records_row[0]["Total"]
        extra_facts.append(f"年度播放记录总数：{total_records} 条")
    
    return monthly_top3, annual_summary, extra_facts

# =========================
# 海报绘制
# =========================

def add_rounded_corners(img, radius):
    """为图片添加圆角"""
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
    output = Image.new('RGBA', img.size, (0, 0, 0, 0))
    output.paste(img.convert('RGBA'), mask=mask)
    return output

def draw_annual_report(year, monthly_top3, annual_summary, extra_facts):
    """绘制年度报告海报"""
    print("\n🎨 正在绘制海报...")
    
    W = 1080
    margin = 60
    
    month_label_w = 65
    poster_w = 170
    poster_h = int(poster_w * 1.4)
    poster_gap = 25
    month_row_h = poster_h + 55
    month_gap = 30
    
    header_h = 180
    months_h = 12 * month_row_h + 11 * month_gap
    summary_h = 400
    extra_h = 60 + len(extra_facts) * 35
    footer_h = 120
    
    H = header_h + months_h + summary_h + extra_h + footer_h + margin * 2
    
    img = Image.new('RGBA', (W, H))
    draw = ImageDraw.Draw(img)
    
    # 深色渐变背景
    for y in range(H):
        t = y / H
        r = int(18 + 8 * t)
        g = int(18 + 12 * t)
        b = int(35 + 18 * t)
        draw.line((0, y, W, y), fill=(r, g, b))
    
    # 字体
    title_font = ImageFont.truetype(FONT_DIR + "msyhbd.ttc", 38)
    subtitle_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 16)
    year_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 14)
    month_font = ImageFont.truetype(FONT_DIR + "msyhbd.ttc", 18)
    month_en_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 11)
    name_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 11)
    dur_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 10)
    rank_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 12)
    summary_title_font = ImageFont.truetype(FONT_DIR + "msyhbd.ttc", 14)
    summary_value_font = ImageFont.truetype(FONT_DIR + "msyhbd.ttc", 24)
    summary_label_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 11)
    fact_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 12)
    brand_font = ImageFont.truetype(FONT_DIR + "msyh.ttc", 12)
    
    text_white = (255, 255, 255)
    text_gray = (140, 140, 155)
    text_light = (190, 190, 200)
    accent = (200, 170, 120)
    empty_card = (40, 40, 55)
    month_bg = (35, 35, 50)
    
    month_names = {
        1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR',
        5: 'MAY', 6: 'JUN', 7: 'JUL', 8: 'AUG',
        9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
    }
    
    # Header
    header_y = margin
    
    year_text = str(year)
    bbox = year_font.getbbox(year_text)
    year_w = bbox[2] - bbox[0]
    draw.text(((W - year_w) // 2, header_y + 10), year_text, fill=text_gray, font=year_font)
    
    title = "年度观影报告"
    bbox = title_font.getbbox(title)
    title_w = bbox[2] - bbox[0]
    draw.text(((W - title_w) // 2, header_y + 35), title, fill=text_white, font=title_font)
    
    subtitle = "Annual Playback Report"
    bbox = subtitle_font.getbbox(subtitle)
    sub_w = bbox[2] - bbox[0]
    draw.text(((W - sub_w) // 2, header_y + 85), subtitle, fill=text_gray, font=subtitle_font)
    
    line_y = header_y + 130
    draw.line((margin + 150, line_y, W - margin - 150, line_y), fill=(50, 50, 65), width=1)
    
    # 月份模块
    content_y = header_y + 150
    
    for month in range(1, 13):
        row_y = content_y + (month - 1) * (month_row_h + month_gap)
        month_data = monthly_top3.get(month, [])
        
        label_x = margin
        label_y = row_y + (poster_h - 45) // 2
        
        label_bg = Image.new('RGBA', (month_label_w, 45), (*month_bg, 255))
        label_bg = add_rounded_corners(label_bg, 8)
        img.paste(label_bg, (label_x, label_y), label_bg)
        
        month_text = f"{month}月"
        draw.text((label_x + month_label_w // 2, label_y + 8), month_text,
                 fill=text_white, font=month_font, anchor="mt")
        draw.text((label_x + month_label_w // 2, label_y + 30), month_names[month],
                 fill=text_gray, font=month_en_font, anchor="mt")
        
        posters_x = margin + month_label_w + 35
        
        for i in range(3):
            card_x = posters_x + i * (poster_w + poster_gap)
            card_y = row_y
            
            if i < len(month_data):
                item = month_data[i]
                
                poster = item["poster"]
                poster = poster.resize((poster_w, poster_h), Image.Resampling.LANCZOS)
                poster = add_rounded_corners(poster, 10)
                img.paste(poster, (card_x, card_y), poster)
                
                rank_text = f"#{i+1}"
                draw.text((card_x + 8, card_y + 6), rank_text,
                         fill=(255, 255, 255, 150), font=rank_font)
                
                dur_text = sec_to_hm(item["duration"])
                bbox = dur_font.getbbox(dur_text)
                dur_w = bbox[2] - bbox[0]
                draw.text((card_x + poster_w - dur_w - 8, card_y + poster_h - 18),
                         dur_text, fill=(255, 255, 255, 180), font=dur_font)
                
                name = item["name"]
                if len(name) > 12:
                    name = name[:11] + "..."
                bbox = name_font.getbbox(name)
                name_w = bbox[2] - bbox[0]
                draw.text((card_x + (poster_w - name_w) // 2, card_y + poster_h + 8),
                         name, fill=text_light, font=name_font)
            else:
                empty = Image.new('RGBA', (poster_w, poster_h), (*empty_card, 255))
                empty = add_rounded_corners(empty, 10)
                img.paste(empty, (card_x, card_y), empty)
                
                if i == len(month_data):
                    hint = "本月暂无播放记录" if len(month_data) == 0 else ""
                    if hint:
                        bbox = name_font.getbbox(hint)
                        hint_w = bbox[2] - bbox[0]
                        draw.text((card_x + (poster_w - hint_w) // 2, card_y + poster_h // 2 - 6),
                                 hint, fill=text_gray, font=name_font)
    
    # 年度汇总
    summary_y = content_y + months_h + 50
    
    draw.line((margin + 150, summary_y, W - margin - 150, summary_y), fill=(50, 50, 65), width=1)
    
    summary_title = "年度汇总"
    bbox = summary_title_font.getbbox(summary_title)
    st_w = bbox[2] - bbox[0]
    draw.text(((W - st_w) // 2, summary_y + 20), summary_title, fill=accent, font=summary_title_font)
    
    period_text = f"统计周期：{annual_summary['stats_period']}"
    bbox = summary_label_font.getbbox(period_text)
    pt_w = bbox[2] - bbox[0]
    draw.text(((W - pt_w) // 2, summary_y + 48), period_text, fill=text_gray, font=summary_label_font)
    
    card_y = summary_y + 80
    card_w = 200
    card_h = 80
    card_gap = 20
    
    cards_row1 = [
        ("年度总播放时长", sec_to_hm(annual_summary["total_duration"])),
        ("观看作品数", f"{annual_summary['total_items']} 部"),
    ]
    
    row1_w = len(cards_row1) * card_w + (len(cards_row1) - 1) * card_gap
    row1_x = (W - row1_w) // 2
    
    for i, (label, value) in enumerate(cards_row1):
        cx = row1_x + i * (card_w + card_gap)
        
        card_bg = Image.new('RGBA', (card_w, card_h), (35, 35, 50, 255))
        card_bg = add_rounded_corners(card_bg, 10)
        img.paste(card_bg, (cx, card_y), card_bg)
        
        bbox = summary_label_font.getbbox(label)
        lw = bbox[2] - bbox[0]
        draw.text((cx + (card_w - lw) // 2, card_y + 12), label, fill=text_gray, font=summary_label_font)
        
        bbox = summary_value_font.getbbox(value)
        vw = bbox[2] - bbox[0]
        draw.text((cx + (card_w - vw) // 2, card_y + 38), value, fill=accent, font=summary_value_font)
    
    card_y2 = card_y + card_h + 15
    cards_row2 = []
    
    if annual_summary["top_user"]:
        user_name = annual_summary["top_user"]["name"]
        user_dur = sec_to_hm(annual_summary["top_user"]["duration"])
        cards_row2.append(("年度观看最长用户", user_name, user_dur))
    
    if annual_summary["top_client"]:
        cards_row2.append(("最常用客户端", annual_summary["top_client"]["name"], ""))
    
    if cards_row2:
        row2_w = len(cards_row2) * card_w + (len(cards_row2) - 1) * card_gap
        row2_x = (W - row2_w) // 2
        
        for i, item in enumerate(cards_row2):
            cx = row2_x + i * (card_w + card_gap)
            label = item[0]
            value = item[1]
            sub = item[2] if len(item) > 2 else ""
            
            card_bg = Image.new('RGBA', (card_w, card_h), (35, 35, 50, 255))
            card_bg = add_rounded_corners(card_bg, 10)
            img.paste(card_bg, (cx, card_y2), card_bg)
            
            bbox = summary_label_font.getbbox(label)
            lw = bbox[2] - bbox[0]
            draw.text((cx + (card_w - lw) // 2, card_y2 + 10), label, fill=text_gray, font=summary_label_font)
            
            if len(value) > 12:
                value = value[:11] + "..."
            bbox = summary_value_font.getbbox(value)
            vw = bbox[2] - bbox[0]
            draw.text((cx + (card_w - vw) // 2, card_y2 + 32), value, fill=accent, font=summary_value_font)
            
            if sub:
                bbox = summary_label_font.getbbox(sub)
                sw = bbox[2] - bbox[0]
                draw.text((cx + (card_w - sw) // 2, card_y2 + 62), sub, fill=text_gray, font=summary_label_font)
    
    # 补充数据
    if extra_facts:
        facts_y = summary_y + 300
        
        draw.line((margin + 200, facts_y, W - margin - 200, facts_y), fill=(50, 50, 65), width=1)
        
        for i, fact in enumerate(extra_facts):
            fy = facts_y + 25 + i * 32
            draw.ellipse((margin + 100 - 2, fy + 5, margin + 100 + 2, fy + 9), fill=text_gray)
            draw.text((margin + 115, fy), fact, fill=text_light, font=fact_font)
    
    # Footer
    footer_y = H - footer_h
    
    draw.line((margin + 150, footer_y + 10, W - margin - 150, footer_y + 10), fill=(50, 50, 65), width=1)
    
    brand = f"Jellyfin Media · {SITE_NAME}"
    bbox = brand_font.getbbox(brand)
    bw = bbox[2] - bbox[0]
    draw.text(((W - bw) // 2, footer_y + 40), brand, fill=text_gray, font=brand_font)
    
    year_text = str(year)
    bbox = brand_font.getbbox(year_text)
    yw = bbox[2] - bbox[0]
    draw.text(((W - yw) // 2, footer_y + 65), year_text, fill=text_gray, font=brand_font)
    
    # 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    save_path = f"{OUTPUT_DIR}/annual_report_{year}.png"
    img.convert('RGB').save(save_path, quality=95)
    
    print(f"\n✅ 年度报告已生成: {save_path}")
    print(f"   尺寸: {W} × {H}")
    
    return save_path

# =========================
# 主函数
# =========================

def main():
    print("=" * 60)
    print(f"🎬 {REPORT_YEAR} 年度观影报告生成器")
    print("   Annual Playback Report Generator")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"\n❌ 数据库不存在: {DB_PATH}")
        print("   请先运行 weekly_rank_v2.py 拉取数据库")
        return
    
    monthly_top3, annual_summary, fun_facts = get_annual_data(REPORT_YEAR)
    
    poster_path = draw_annual_report(REPORT_YEAR, monthly_top3, annual_summary, fun_facts)
    
    print("\n" + "=" * 60)
    print("✨ 生成完成！")
    print("=" * 60)
    print(f"""
📊 年度统计:
   总播放时长: {sec_to_hm(annual_summary['total_duration'])}
   观看作品数: {annual_summary['total_items']} 部
""")

if __name__ == "__main__":
    main()
