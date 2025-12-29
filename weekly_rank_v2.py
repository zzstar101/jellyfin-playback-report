# -*- coding: utf-8 -*-
"""
Jellyfin 播放周榜 V2（三分类）
- 电影 / 电视剧 / 番剧 各 Top 3
- 统计本周片王
- 全新海报设计

GitHub: https://github.com/zzstar101/jellyfin-playback-report
"""

import sqlite3
import requests
import datetime
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# 尝试导入 paramiko (用于 SSH)
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# =========================
# 🔧 配置区（请修改为你的配置）
# =========================

# NAS SSH 配置（用于拉取播放记录数据库）
NAS_HOST = "YOUR_NAS_HOST"           # NAS 地址
NAS_PORT = 22                         # SSH 端口
NAS_USER = "YOUR_NAS_USER"           # SSH 用户名
NAS_PASSWORD = "YOUR_NAS_PASSWORD"   # SSH 密码
NAS_DB_PATH = "/path/to/playback_reporting.db"  # 数据库路径

# 本地数据库缓存
DB_CACHE_DIR = "./cache"
DB_PATH = f"{DB_CACHE_DIR}/playback_reporting.db"

# Jellyfin 服务器
JELLYFIN_URL = "https://your-jellyfin-server.com"
JELLYFIN_API_KEY = "YOUR_JELLYFIN_API_KEY"

# Server 酱推送（可选）
SERVERCHAN_KEY = "YOUR_SERVERCHAN_KEY"

# Lsky 图床（可选）
LSKY_URL = "https://your-lsky-server.com"
LSKY_TOKEN = "YOUR_LSKY_TOKEN"

# 站点名称
SITE_NAME = "YOUR_SITE_NAME"

# 榜单配置
TOP_N = 3

# 媒体库分类映射
LIBRARY_MAPPING = {
    "电影": "电影",
    "Movies": "电影",
    "电视剧": "电视剧",
    "TV Shows": "电视剧",
    "番剧": "番剧",
    "Anime": "番剧"
}

# 时区
TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))

# 海报输出目录
POSTER_DIR = "./posters"

# 字体（请根据系统修改）
# Windows: "C:/Windows/Fonts/msyh.ttc"
# Linux: "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

# =========================
# 辅助函数
# =========================

def ensure_dirs():
    """确保必要的目录存在"""
    Path(DB_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    Path(POSTER_DIR).mkdir(parents=True, exist_ok=True)


def fetch_database():
    """从 NAS 拉取数据库"""
    print(f"📥 正在从 NAS 拉取数据库...")
    
    if HAS_PARAMIKO:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            print(f"  → 连接到 {NAS_USER}@{NAS_HOST}:{NAS_PORT}")
            ssh.connect(
                hostname=NAS_HOST,
                port=NAS_PORT,
                username=NAS_USER,
                password=NAS_PASSWORD,
                timeout=30,
                look_for_keys=False,
                allow_agent=False
            )
            
            print(f"  → 下载文件: {NAS_DB_PATH}")
            stdin, stdout, stderr = ssh.exec_command(f'cat "{NAS_DB_PATH}"')
            
            file_data = stdout.read()
            error_data = stderr.read()
            
            if error_data:
                raise Exception(f"SSH 命令错误: {error_data.decode()}")
            
            with open(DB_PATH, 'wb') as f:
                f.write(file_data)
            
            ssh.close()
            print(f"✅ 数据库拉取成功: {DB_PATH}")
            return True
            
        except Exception as e:
            print(f"❌ 拉取失败: {e}")
            return False
    else:
        print("❌ 未安装 paramiko")
        return False


def query(sql, params=()):
    """执行 SQL 查询"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def sec_to_str(sec: int) -> str:
    """秒数转时间字符串"""
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


def extract_series_name(item_name: str) -> str:
    """从 Episode 名称提取剧名"""
    if " - " in item_name:
        return item_name.split(" - ")[0].strip()
    return item_name.strip()


def get_week_range():
    """计算上周的时间范围（周一早上运行，统计上周一到上周日）"""
    now = datetime.datetime.now(TIMEZONE)
    weekday = now.weekday()
    # 计算本周一
    this_monday = (now - datetime.timedelta(days=weekday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # 上周一 = 本周一 - 7天
    week_start = this_monday - datetime.timedelta(days=7)
    # 上周日 = 上周一 + 6天
    week_end = (week_start + datetime.timedelta(days=6)).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    
    week_start_str = week_start.date().isoformat()
    week_end_str = week_end.date().isoformat()
    
    return week_start, week_end, week_start_str, week_end_str


def search_jellyfin_item(name, item_type="Series"):
    """通过名称搜索 Jellyfin 媒体项"""
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


def jellyfin_poster(item_id):
    """获取 Jellyfin 封面"""
    url = f"{JELLYFIN_URL}/Items/{item_id}/Images/Primary"
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return Image.open(BytesIO(r.content))
    except:
        pass
    return None


def add_rounded_corners(img, radius):
    """为图片添加圆角"""
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
    output = Image.new('RGBA', img.size, (0, 0, 0, 0))
    output.paste(img.convert('RGBA'), mask=mask)
    return output


def get_week_data():
    """统计本周播放数据"""
    week_start, week_end, week_start_str, week_end_str = get_week_range()
    
    since = week_start.isoformat()
    until = week_end.isoformat()

    print("\n📊 正在统计播放数据...")

    # 1. 电影榜
    print("  → 统计电影...")
    movies = query("""
        SELECT
            ItemName AS Name,
            ItemId,
            COUNT(*) AS cnt,
            SUM(PlayDuration) AS dur
        FROM PlaybackActivity
        WHERE ItemType = 'Movie'
          AND DateCreated >= ?
          AND DateCreated <= ?
        GROUP BY ItemName
        ORDER BY dur DESC, cnt DESC
        LIMIT ?
    """, (since, until, TOP_N))

    # 2. 剧集
    print("  → 统计剧集...")
    raw_eps = query("""
        SELECT
            ItemName AS Name,
            ItemId,
            COUNT(*) AS cnt,
            SUM(PlayDuration) AS dur
        FROM PlaybackActivity
        WHERE ItemType = 'Episode'
          AND DateCreated >= ?
          AND DateCreated <= ?
        GROUP BY ItemName
    """, (since, until))

    # 按剧集聚合并分类
    series_data = {}
    
    for r in raw_eps:
        series_name = extract_series_name(r["Name"])
        if series_name not in series_data:
            series_data[series_name] = {
                "Name": series_name,
                "cnt": 0,
                "dur": 0,
                "EpisodeId": r["ItemId"],
                "category": None
            }
        series_data[series_name]["cnt"] += r["cnt"]
        series_data[series_name]["dur"] += r["dur"]

    # 通过 Jellyfin API 分类
    print("  → 分类剧集（电视剧/番剧）...")
    tv_shows_list = []
    anime_list = []
    
    for series_name, data in series_data.items():
        series_id = search_jellyfin_item(series_name, "Series")
        
        if series_id:
            try:
                url = f"{JELLYFIN_URL}/Items/{series_id}"
                headers = {"X-Emby-Token": JELLYFIN_API_KEY}
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    item_data = r.json()
                    genres = item_data.get("Genres", [])
                    tags = item_data.get("Tags", [])
                    
                    is_anime = any(g in ["Animation", "Anime", "动画", "番剧"] for g in genres + tags)
                    
                    if is_anime:
                        anime_list.append({**data, "SeriesId": series_id})
                    else:
                        tv_shows_list.append({**data, "SeriesId": series_id})
                else:
                    anime_list.append({**data, "SeriesId": series_id})
            except:
                anime_list.append({**data, "SeriesId": series_id})
        else:
            anime_list.append(data)

    tv_shows = sorted(tv_shows_list, key=lambda x: (x["dur"], x["cnt"]), reverse=True)[:TOP_N]
    anime = sorted(anime_list, key=lambda x: (x["dur"], x["cnt"]), reverse=True)[:TOP_N]

    # 3. 本周片王
    print("  → 统计本周片王...")
    top_users = query("""
        SELECT
            UserId,
            SUM(PlayDuration) AS total_dur
        FROM PlaybackActivity
        WHERE DateCreated >= ?
          AND DateCreated <= ?
        GROUP BY UserId
        ORDER BY total_dur DESC
        LIMIT 1
    """, (since, until))

    top_user = None
    if top_users:
        user_id = top_users[0]["UserId"]
        total_dur = top_users[0]["total_dur"]
        
        try:
            url = f"{JELLYFIN_URL}/Users/{user_id}"
            headers = {"X-Emby-Token": JELLYFIN_API_KEY}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                user_data = r.json()
                user_name = user_data.get("Name", "Unknown")
            else:
                user_name = "Unknown"
        except:
            user_name = "Unknown"
        
        top_user = {
            "name": user_name,
            "duration": total_dur
        }

    return movies, tv_shows, anime, top_user, week_start_str, week_end_str


def get_poster_filename(week_end_str):
    """生成海报文件名"""
    return f"{POSTER_DIR}/weekly-poster-{week_end_str}.png"


def draw_poster_v2(movies, tv_shows, anime, top_user, poster_path):
    """生成播放周榜海报"""
    # === 设计参数 ===
    W = 1080
    margin_x = 60
    margin_top = 50
    col_gap = 40
    
    col_width = (W - margin_x * 2 - col_gap * 2) // 3
    col_positions = [
        margin_x,
        margin_x + col_width + col_gap,
        margin_x + (col_width + col_gap) * 2
    ]
    
    card_w = col_width
    card_h = int(card_w * 1.4)
    card_gap = 40
    card_radius = 12
    
    header_h = 130
    col_title_h = 45
    card_area_h = 3 * card_h + 2 * card_gap
    footer_h = 70
    content_padding = 30
    
    H = margin_top + header_h + col_title_h + card_area_h + content_padding + footer_h
    
    categories = [
        ('电影', 'Movie', movies, (145, 150, 160)),
        ('电视剧', 'TV Series', tv_shows, (140, 155, 150)),
        ('番剧', 'Anime', anime, (155, 145, 165)),
    ]
    
    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)

    # 背景渐变
    for y in range(H):
        t = y / H
        r = int(250 - 35 * t)
        g = int(240 - 50 * t)
        b = int(235 - 25 * t)
        draw.line((0, y, W, y), fill=(r, g, b))

    # 字体
    title_font = ImageFont.truetype(FONT_PATH.replace("msyh", "msyhbd"), 36)
    sub_font = ImageFont.truetype(FONT_PATH, 14)
    col_title_font = ImageFont.truetype(FONT_PATH.replace("msyh", "msyhbd"), 16)
    col_sub_font = ImageFont.truetype(FONT_PATH, 11)
    rank_font = ImageFont.truetype(FONT_PATH, 12)
    empty_font = ImageFont.truetype(FONT_PATH, 12)
    brand_font = ImageFont.truetype(FONT_PATH, 12)
    name_font = ImageFont.truetype(FONT_PATH, 11)

    text_primary = (60, 60, 65)
    text_secondary = (120, 120, 130)
    text_tertiary = (160, 160, 170)
    empty_bg = (220, 220, 225)
    empty_text = (170, 170, 180)

    # Header
    header_y = margin_top
    draw.text((margin_x, header_y), "播放周榜", fill=text_primary, font=title_font)
    draw.text((margin_x, header_y + 45), "Weekly Playback Statistics", fill=text_secondary, font=sub_font)

    # Content
    content_y = margin_top + header_h
    
    for i, (cat_cn, cat_en, items, color) in enumerate(categories):
        col_x = col_positions[i]
        count = len(items) if items else 0
        
        draw.text((col_x, content_y), cat_cn, fill=text_primary, font=col_title_font)
        draw.text((col_x, content_y + 22), cat_en, fill=text_tertiary, font=col_sub_font)
        
        cards_y = content_y + col_title_h
        
        for j in range(3):
            card_y = cards_y + j * (card_h + card_gap)
            rank = j + 1
            
            if items and j < count:
                item = items[j]
                poster_img = None
                
                if cat_en == 'Movie':
                    mid = search_jellyfin_item(item["Name"], "Movie")
                    if mid:
                        poster_img = jellyfin_poster(mid)
                else:
                    if "SeriesId" in item:
                        poster_img = jellyfin_poster(item["SeriesId"])
                    else:
                        sid = search_jellyfin_item(item["Name"], "Series")
                        if sid:
                            poster_img = jellyfin_poster(sid)
                
                if poster_img:
                    poster_img = poster_img.resize((card_w, card_h), Image.Resampling.LANCZOS)
                    rounded_poster = add_rounded_corners(poster_img, card_radius)
                    img.paste(rounded_poster, (col_x, card_y), rounded_poster)
                else:
                    card = Image.new('RGBA', (card_w, card_h), (*color, 255))
                    rounded_card = add_rounded_corners(card, card_radius)
                    img.paste(rounded_card, (col_x, card_y), rounded_card)
                    
                    placeholder_font = ImageFont.truetype(FONT_PATH, 14)
                    name = item["Name"]
                    max_chars = 12
                    if len(name) > max_chars:
                        name = name[:max_chars] + "..."
                    
                    bbox = placeholder_font.getbbox(name)
                    name_w = bbox[2] - bbox[0]
                    name_x = col_x + (card_w - name_w) // 2
                    name_y = card_y + card_h // 2 - 10
                    draw.text((name_x, name_y), name, fill=(255, 255, 255, 220), font=placeholder_font)
                
                draw.text((col_x + 12, card_y + 10), str(rank), 
                         fill=(255, 255, 255, 180), font=rank_font)
                
                item_name = item["Name"]
                max_chars = 30
                if len(item_name) > max_chars:
                    item_name = item_name[:max_chars] + "..."
                bbox = name_font.getbbox(item_name)
                item_name_w = bbox[2] - bbox[0]
                item_name_x = col_x + (card_w - item_name_w) // 2
                item_name_y = card_y + card_h + 6
                draw.text((item_name_x, item_name_y), item_name, fill=text_secondary, font=name_font)
            else:
                placeholder = Image.new('RGBA', (card_w, card_h), (*empty_bg, 255))
                rounded_placeholder = add_rounded_corners(placeholder, card_radius)
                img.paste(rounded_placeholder, (col_x, card_y), rounded_placeholder)
                
                if j == count:
                    hint = "本周暂无播放记录"
                    bbox = empty_font.getbbox(hint)
                    hint_w = bbox[2] - bbox[0]
                    hint_x = col_x + (card_w - hint_w) // 2
                    hint_y = card_y + card_h // 2 - 8
                    draw.text((hint_x, hint_y), hint, fill=empty_text, font=empty_font)

    # Footer
    footer_y = H - footer_h + 10
    
    import datetime as dt
    now = dt.datetime.now()
    week_num = now.isocalendar()[1]
    draw.text((margin_x, footer_y), f"Week {week_num} · {now.year}", 
             fill=text_tertiary, font=brand_font)
    
    draw.text((margin_x, footer_y + 20), f"Jellyfin Media · {SITE_NAME}", 
             fill=text_secondary, font=brand_font)

    img.convert('RGB').save(poster_path)
    print(f"✅ 海报已生成: {poster_path}")


def upload_to_lsky(file_path):
    """上传到 Lsky 图床"""
    print(f"\n📤 正在上传海报...")
    try:
        url = f"{LSKY_URL}/api/v1/upload"
        headers = {"Authorization": f"Bearer {LSKY_TOKEN}"}
        
        with open(file_path, 'rb') as f:
            files = {'file': f}
            r = requests.post(url, headers=headers, files=files, timeout=30)
        
        if r.status_code == 200:
            data = r.json()
            if data.get('status'):
                img_url = data['data']['links']['url']
                print(f"✅ 上传成功: {img_url}")
                return img_url
    except Exception as e:
        print(f"❌ 上传失败: {e}")
    return None


def send_serverchan(desp):
    """推送到 Server 酱"""
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    try:
        r = requests.post(url, data={
            "title": f"{SITE_NAME} Jellyfin 播放周榜",
            "desp": desp
        }, timeout=10)
        
        if r.status_code == 200:
            return True
    except:
        pass
    return False


def build_text(movies, tv_shows, anime, top_user, week_start_str, week_end_str):
    """生成文本榜单"""
    lines = [f"【{SITE_NAME} Jellyfin 播放周榜】\n\n"]
    lines.append(f"统计周期: {week_start_str} ~ {week_end_str}\n\n")

    if top_user:
        lines.append(f"🏆 本周片王: {top_user['name']}\n")
        lines.append(f"   观看时长: {sec_to_str(top_user['duration'])}\n\n")

    lines.append("📽️ 电影 Top 3:\n\n")
    if movies:
        for i, r in enumerate(movies, 1):
            lines.append(f"{i}. {r['Name']}\n")
            lines.append(f"   播放次数: {r['cnt']}  时长: {sec_to_str(r['dur'])}\n")
    else:
        lines.append("该类别本周没有播放记录\n")

    lines.append("\n📺 电视剧 Top 3:\n\n")
    if tv_shows:
        for i, r in enumerate(tv_shows, 1):
            lines.append(f"{i}. {r['Name']}\n")
            lines.append(f"   播放次数: {r['cnt']}  时长: {sec_to_str(r['dur'])}\n")
    else:
        lines.append("该类别本周没有播放记录\n")

    lines.append("\n🎌 番剧 Top 3:\n\n")
    if anime:
        for i, r in enumerate(anime, 1):
            lines.append(f"{i}. {r['Name']}\n")
            lines.append(f"   播放次数: {r['cnt']}  时长: {sec_to_str(r['dur'])}\n")
    else:
        lines.append("该类别本周没有播放记录\n")

    lines.append(f"\n#WeekRanks  {datetime.date.today().isoformat()}")
    
    return "".join(lines)


def main():
    print("=" * 50)
    print("🎬 Jellyfin 播放周榜生成器 V2")
    print("=" * 50)
    
    ensure_dirs()
    
    # 拉取数据库（每次都重新拉取以获取最新数据）
    print("\n📥 正在获取最新播放数据...")
    if not fetch_database():
        print("\n⚠️  数据库拉取失败，尝试使用缓存数据")
        if not os.path.exists(DB_PATH):
            print("❌ 缓存数据也不存在，无法继续")
            return
        print("ℹ️  使用缓存数据库")
    
    movies, tv_shows, anime, top_user, week_start_str, week_end_str = get_week_data()
    
    text = build_text(movies, tv_shows, anime, top_user, week_start_str, week_end_str)
    print("\n" + "=" * 50)
    print(text)
    print("=" * 50)
    
    print("\n🎨 正在生成海报...")
    poster_path = get_poster_filename(week_end_str)
    draw_poster_v2(movies, tv_shows, anime, top_user, poster_path)
    
    img_url = upload_to_lsky(poster_path)
    
    print("\n📮 正在推送...")
    if img_url:
        desp = f"![周榜]({img_url})\n\n{text}"
        if send_serverchan(desp):
            print("✅ 推送成功")
        else:
            print("⚠️  推送失败")
    else:
        if send_serverchan(text):
            print("✅ 推送成功（无图片）")

    print("\n" + "=" * 50)
    print("✨ 任务完成！")
    print("=" * 50)


if __name__ == "__main__":
    main()
