# -*- coding: utf-8 -*-
"""
Jellyfin 播放周榜 V3（含订阅日历）
- 电影 / 电视剧 / 番剧 各 Top 3
- 统计本周片王
- 本周放送日历（来自 MoviePilot 订阅）
- 全新海报设计
"""

import sqlite3
import requests
import datetime
import subprocess
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from collections import defaultdict
from typing import Dict, List, Any, Optional

# 尝试导入 paramiko (用于 SSH)
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# =========================
# 配置区
# =========================

# NAS SSH 配置
NAS_HOST = "nas.nerv-base.com"
NAS_PORT = 22
NAS_USER = "zzstar"
NAS_PASSWORD = "Zhan061207"
NAS_DB_PATH = "/volume1/docker/jellyfin/config/data/playback_reporting.db"

# 本地数据库缓存
DB_CACHE_DIR = "./cache"
DB_PATH = f"{DB_CACHE_DIR}/playback_reporting.db"

# Jellyfin 服务器
JELLYFIN_URL = "https://jellyfin.nerv-base.com"
JELLYFIN_API_KEY = "742c4c287fe94690913290bc84d39db1"

# MoviePilot 配置
MOVIEPILOT_URL = "https://mp.nerv-base.com"
MOVIEPILOT_API_TOKEN = "NewSecureKey_2025_XYZ789"
MOVIEPILOT_USERNAME = "admin"
MOVIEPILOT_PASSWORD = "admin123"

# Server 酱
SERVERCHAN_KEY = "SCT302181TX4Ms0Nxj1k6Hg15wyAiivU65"

# Lsky 图床
LSKY_URL = "https://img.nerv-base.com"
LSKY_TOKEN = "1|Gi3s3p5vkzfD74A8N1SIkdhqFUrWPrWHHu1E8HWu"

# 站点名称
SITE_NAME = "NERV-BASE"

# 榜单配置
TOP_N = 3

# 媒体库父项 ID
LIBRARY_ANIME = "7dd48b4cf954f687df24682cfc5ce9f7"
LIBRARY_TV = "3f3929b48afa16be4dd97fb4e178c796"

# 时区
TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))

# 海报输出目录
POSTER_DIR = "./posters"

# 字体
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

# 是否启用推送（测试时设为 False）
ENABLE_PUSH = True


# =========================
# MoviePilot API 客户端
# =========================

class MoviePilotClient:
    """MoviePilot API 客户端"""
    
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url
        self.api_token = api_token
        self.access_token: Optional[str] = None
    
    def login(self, username: str, password: str) -> bool:
        """OAuth2 登录获取 access_token"""
        try:
            url = f"{self.base_url}/api/v1/login/access-token"
            resp = requests.post(url, data={
                "username": username,
                "password": password
            }, timeout=30)
            
            if resp.status_code == 200:
                self.access_token = resp.json().get("access_token")
                return True
        except Exception as e:
            print(f"  [!] MoviePilot 登录失败: {e}")
        return False
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """获取认证请求头"""
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}
    
    def get_subscriptions(self) -> List[Dict]:
        """获取订阅列表"""
        try:
            url = f"{self.base_url}/api/v1/subscribe/list?token={self.api_token}"
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"  [!] 获取订阅失败: {e}")
        return []
    
    def get_episodes(self, tmdbid: int, season: int) -> List[Dict]:
        """获取剧集信息"""
        try:
            url = f"{self.base_url}/api/v1/tmdb/{tmdbid}/{season}"
            resp = requests.get(url, headers=self._get_auth_headers(), timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return []
    
    def get_movie_info(self, tmdbid: int) -> Optional[Dict]:
        """获取电影信息"""
        try:
            # 使用 media 接口获取电影信息
            url = f"{self.base_url}/api/v1/media/tmdb:{tmdbid}?type_name=%E7%94%B5%E5%BD%B1"
            resp = requests.get(url, headers=self._get_auth_headers(), timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return None


def get_weekly_calendar() -> List[Dict]:
    """
    获取本周放送日历（周一到周日）
    返回按日期分组的剧集列表
    """
    print("\n📅 正在获取订阅日历...")
    
    client = MoviePilotClient(MOVIEPILOT_URL, MOVIEPILOT_API_TOKEN)
    
    # 登录
    if not client.login(MOVIEPILOT_USERNAME, MOVIEPILOT_PASSWORD):
        print("  [!] MoviePilot 登录失败，跳过日历")
        return []
    
    print("  [OK] MoviePilot 登录成功")
    
    # 获取订阅
    subscriptions = client.get_subscriptions()
    print(f"  -> 获取到 {len(subscriptions)} 条订阅")
    
    # 计算本周范围（周一到周日）
    now = datetime.datetime.now(TIMEZONE)
    weekday = now.weekday()
    week_start = (now - datetime.timedelta(days=weekday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)
    
    # 收集本周剧集和电影
    calendar = defaultdict(list)
    
    for sub in subscriptions:
        tmdbid = sub.get('tmdbid')
        name = sub.get('name')
        poster = sub.get('poster')
        season = sub.get('season')
        
        # 有 season 字段的是电视剧，获取剧集信息
        if season:
            episodes = client.get_episodes(tmdbid, season)
            for ep in episodes:
                air_date_str = ep.get('air_date')
                if air_date_str:
                    try:
                        air_date = datetime.datetime.strptime(air_date_str, '%Y-%m-%d')
                        air_date = air_date.replace(tzinfo=TIMEZONE)
                        
                        if week_start.date() <= air_date.date() <= week_end.date():
                            calendar[air_date_str].append({
                                'name': name,
                                'season': season,
                                'episode': ep.get('episode_number'),
                                'title': ep.get('name'),
                                'poster': poster,
                                'weekday': air_date.weekday(),
                            })
                    except ValueError:
                        pass
        else:
            # 没有 season 字段的是电影，获取电影信息
            movie_info = client.get_movie_info(tmdbid)
            if movie_info:
                release_date = movie_info.get('release_date')
                if release_date:
                    try:
                        release_dt = datetime.datetime.strptime(release_date, '%Y-%m-%d')
                        release_dt = release_dt.replace(tzinfo=TIMEZONE)
                        
                        if week_start.date() <= release_dt.date() <= week_end.date():
                            calendar[release_date].append({
                                'name': name,
                                'title': movie_info.get('title', name),
                                'poster': poster,
                                'weekday': release_dt.weekday(),
                            })
                    except ValueError:
                        pass
    
    # 转换为列表格式
    result = []
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    for date_str in sorted(calendar.keys()):
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        weekday_idx = date_obj.weekday()
        
        result.append({
            'date': date_str,
            'weekday': weekday_names[weekday_idx],
            'weekday_idx': weekday_idx,
            'episodes': calendar[date_str]
        })
    
    total_eps = sum(len(d['episodes']) for d in result)
    print(f"  -> 本周共 {total_eps} 集待播出")
    
    return result


# =========================
# 辅助函数
# =========================

def ensure_dirs():
    """确保必要的目录存在"""
    Path(DB_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    Path(POSTER_DIR).mkdir(parents=True, exist_ok=True)


def fetch_database():
    """从 NAS 拉取数据库"""
    print(f"  -> 正在从 NAS 拉取数据库...")
    
    if HAS_PARAMIKO:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=NAS_HOST,
                port=NAS_PORT,
                username=NAS_USER,
                password=NAS_PASSWORD,
                timeout=30,
                look_for_keys=False,
                allow_agent=False
            )
            
            stdin, stdout, stderr = ssh.exec_command(f'cat "{NAS_DB_PATH}"')
            
            file_data = stdout.read()
            error_data = stderr.read()
            
            if error_data:
                raise Exception(f"SSH 命令错误: {error_data.decode()}")
            
            with open(DB_PATH, 'wb') as f:
                f.write(file_data)
            
            ssh.close()
            print(f"  [OK] 数据库拉取成功")
            return True
            
        except Exception as e:
            print(f"  [!] 拉取失败: {e}")
            return False
    else:
        print("  [!] 未安装 paramiko")
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


def classify_by_parent_id(parent_id):
    """通过媒体库 ParentId 判断剧集类型"""
    if parent_id == LIBRARY_ANIME:
        return "anime"
    elif parent_id == LIBRARY_TV:
        return "tv"
    else:
        return "tv"


def get_week_range():
    """计算上周的时间范围"""
    now = datetime.datetime.now(TIMEZONE)
    weekday = now.weekday()
    this_monday = (now - datetime.timedelta(days=weekday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_start = this_monday - datetime.timedelta(days=7)
    week_end = (week_start + datetime.timedelta(days=6)).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    
    week_start_str = week_start.date().isoformat()
    week_end_str = week_end.date().isoformat()
    
    return week_start, week_end, week_start_str, week_end_str


def search_jellyfin_item(name, item_type="Series", with_parent=False):
    """通过名称搜索 Jellyfin 媒体项"""
    try:
        url = f"{JELLYFIN_URL}/Items"
        params = {
            "searchTerm": name,
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "Limit": 1,
            "Fields": "ParentId" if with_parent else ""
        }
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("Items", [])
            if items:
                item = items[0]
                if with_parent:
                    return item.get("Id"), item.get("ParentId", "")
                return item.get("Id")
    except:
        pass
    return (None, "") if with_parent else None


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
    print("  -> 统计电影...")
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
    print("  -> 统计剧集...")
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

    print("  -> 分类剧集...")
    tv_shows_list = []
    anime_list = []
    
    for series_name, data in series_data.items():
        result = search_jellyfin_item(series_name, "Series", with_parent=True)
        series_id, parent_id = result if result else (None, "")
        
        category = classify_by_parent_id(parent_id)
        
        if series_id:
            if category == "anime":
                anime_list.append({**data, "SeriesId": series_id})
            else:
                tv_shows_list.append({**data, "SeriesId": series_id})
        else:
            tv_shows_list.append(data)

    tv_shows = sorted(tv_shows_list, key=lambda x: (x["dur"], x["cnt"]), reverse=True)[:TOP_N]
    anime = sorted(anime_list, key=lambda x: (x["dur"], x["cnt"]), reverse=True)[:TOP_N]

    # 3. 本周片王
    print("  -> 统计本周片王...")
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


def fetch_tmdb_poster(poster_path_str: str) -> Optional[Image.Image]:
    """从 TMDB 获取海报图片"""
    if not poster_path_str:
        return None
    try:
        # TMDB 海报 URL
        url = f"https://image.tmdb.org/t/p/w200{poster_path_str}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return Image.open(BytesIO(resp.content))
    except:
        pass
    return None


def draw_poster_v3(movies, tv_shows, anime, top_user, calendar, poster_path):
    """
    生成播放周榜海报 V3
    新增：本周放送日历区域（横向7列布局）
    """
    # === 设计参数 ===
    W = 1080
    margin_x = 40
    margin_top = 50
    col_gap = 30
    
    # 三列等宽（播放榜）
    rank_col_width = (W - margin_x * 2 - col_gap * 2) // 3
    rank_col_positions = [
        margin_x,
        margin_x + rank_col_width + col_gap,
        margin_x + (rank_col_width + col_gap) * 2
    ]
    
    # 卡片尺寸
    card_w = rank_col_width
    card_h = int(card_w * 1.4)
    card_gap = 40
    card_radius = 12
    
    # 区域高度
    header_h = 130
    col_title_h = 45
    card_area_h = 3 * card_h + 2 * card_gap
    
    # 日历区域参数（横向平铺）
    calendar_title_h = 60
    cal_item_w = 140  # 单个剧集卡片宽度
    cal_item_h = 240  # 单个剧集卡片高度（海报+文字）
    cal_poster_w = 120  # 海报宽度
    cal_poster_h = 180  # 海报高度
    cal_item_gap = 15  # 卡片间距
    cal_date_w = 80  # 日期标签宽度
    cal_row_gap = 25  # 行间距
    
    # 计算日历区域高度（每天一行）
    calendar_rows = len([d for d in calendar if d['episodes']]) if calendar else 0
    calendar_area_h = calendar_title_h + calendar_rows * (cal_item_h + cal_row_gap) + 30
    
    footer_h = 70
    content_padding = 30
    section_gap = 50
    
    # 总高度
    H = margin_top + header_h + col_title_h + card_area_h + content_padding
    H += section_gap + calendar_area_h
    H += footer_h
    
    # === 分类数据 ===
    categories = [
        ('电影', 'Movie', movies, (145, 150, 160)),
        ('电视剧', 'TV Series', tv_shows, (140, 155, 150)),
        ('番剧', 'Anime', anime, (155, 145, 165)),
    ]
    
    # === 创建画布 ===
    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)

    # === 背景渐变 ===
    for y in range(H):
        t = y / H
        r = int(250 - 35 * t)
        g = int(240 - 50 * t)
        b = int(235 - 25 * t)
        draw.line((0, y, W, y), fill=(r, g, b))

    # === 字体 ===
    title_font = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 36)
    sub_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
    col_title_font = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 16)
    col_sub_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
    rank_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    empty_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    brand_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    name_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
    
    # 日历字体
    cal_title_font = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 20)
    cal_date_font = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 18)
    cal_name_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    cal_ep_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
    cal_empty_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)

    # === 颜色系统 ===
    text_primary = (60, 60, 65)
    text_secondary = (120, 120, 130)
    text_tertiary = (160, 160, 170)
    empty_bg = (220, 220, 225)
    empty_text = (170, 170, 180)
    
    # 日历颜色
    cal_bg = (240, 240, 245)
    cal_card_bg = (250, 250, 252)

    # === Header ===
    header_y = margin_top
    draw.text((margin_x, header_y), "播放周榜", fill=text_primary, font=title_font)
    draw.text((margin_x, header_y + 45), "Weekly Playback Statistics", fill=text_secondary, font=sub_font)

    # === Content: 三列布局 ===
    content_y = margin_top + header_h
    
    for i, (cat_cn, cat_en, items, color) in enumerate(categories):
        col_x = rank_col_positions[i]
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
                    
                    placeholder_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
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

    # === 日历区域（横向平铺布局）===
    calendar_y = content_y + col_title_h + card_area_h + content_padding + section_gap
    
    # 日历标题
    draw.text((margin_x, calendar_y), "本周放送", fill=text_primary, font=cal_title_font)
    draw.text((margin_x + 80, calendar_y + 3), "This Week's Airing", fill=text_tertiary, font=col_sub_font)
    
    # 开始绘制各天的剧集（横向平铺）
    current_y = calendar_y + calendar_title_h
    
    for day in calendar:
        episodes = day['episodes']
        if not episodes:
            continue
        
        # 日期标签（左侧）
        date_str = f"{day['date'][5:]}\n{day['weekday']}"
        date_lines = date_str.split('\n')
        date_y = current_y + 10
        for line in date_lines:
            bbox = cal_date_font.getbbox(line)
            line_w = bbox[2] - bbox[0]
            line_x = margin_x + (cal_date_w - line_w) // 2
            draw.text((line_x, date_y), line, fill=text_primary, font=cal_date_font)
            date_y += 25
        
        # 剧集横向排列（从日期标签右侧开始）
        items_x = margin_x + cal_date_w + 20
        max_items_per_row = (W - items_x - margin_x) // (cal_item_w + cal_item_gap)
        
        for ep_idx, ep in enumerate(episodes[:max_items_per_row]):  # 最多一行
            ep_x = items_x + ep_idx * (cal_item_w + cal_item_gap)
            
            # 获取海报
            poster_img = fetch_tmdb_poster(ep.get('poster'))
            
            # 海报居中位置
            poster_x = ep_x + (cal_item_w - cal_poster_w) // 2
            
            if poster_img:
                poster_img = poster_img.resize((cal_poster_w, cal_poster_h), Image.Resampling.LANCZOS)
                rounded_poster = add_rounded_corners(poster_img, 6)
                img.paste(rounded_poster, (poster_x, current_y), rounded_poster)
            else:
                # 占位背景
                placeholder = Image.new('RGBA', (cal_poster_w, cal_poster_h), (220, 220, 225, 255))
                rounded_placeholder = add_rounded_corners(placeholder, 6)
                img.paste(rounded_placeholder, (poster_x, current_y), rounded_placeholder)
            
            # 剧名（居中，截断）
            ep_name = ep['name']
            max_name_chars = 10
            if len(ep_name) > max_name_chars:
                ep_name = ep_name[:max_name_chars] + ".."
            
            bbox = cal_name_font.getbbox(ep_name)
            name_w = bbox[2] - bbox[0]
            name_x = ep_x + (cal_item_w - name_w) // 2
            name_y = current_y + cal_poster_h + 5
            draw.text((name_x, name_y), ep_name, fill=text_primary, font=cal_name_font)
            
            # 如果有季号集数则显示（电视剧）
            if 'season' in ep and 'episode' in ep:
                ep_info = f"S{ep['season']}E{ep['episode']}"
                bbox = cal_ep_font.getbbox(ep_info)
                info_w = bbox[2] - bbox[0]
                info_x = ep_x + (cal_item_w - info_w) // 2
                info_y = name_y + 18
                draw.text((info_x, info_y), ep_info, fill=text_secondary, font=cal_ep_font)
        
        # 如果超过显示数量，显示 +N
        if len(episodes) > max_items_per_row:
            more_x = items_x + max_items_per_row * (cal_item_w + cal_item_gap)
            more_y = current_y + cal_item_h // 2
            more_text = f"+{len(episodes) - max_items_per_row}"
            draw.text((more_x, more_y), more_text, fill=text_tertiary, font=cal_ep_font)
        
        current_y += cal_item_h + cal_row_gap

    # === Footer ===
    footer_y = H - footer_h + 10
    
    now = datetime.datetime.now()
    week_num = now.isocalendar()[1]
    draw.text((margin_x, footer_y), f"Week {week_num} . {now.year}", 
             fill=text_tertiary, font=brand_font)
    
    draw.text((margin_x, footer_y + 20), f"Jellyfin Media . {SITE_NAME}", 
             fill=text_secondary, font=brand_font)

    # 保存
    img.convert('RGB').save(poster_path)
    print(f"  [OK] 海报已生成: {poster_path}")


def upload_to_lsky(file_path):
    """上传到 Lsky 图床"""
    print(f"\n  -> 正在上传海报...")
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
                print(f"  [OK] 上传成功: {img_url}")
                return img_url
    except Exception as e:
        print(f"  [!] 上传失败: {e}")
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


def build_text(movies, tv_shows, anime, top_user, calendar, week_start_str, week_end_str):
    """生成文本榜单"""
    lines = [f"【{SITE_NAME} Jellyfin 播放周榜】\n\n"]
    lines.append(f"统计周期: {week_start_str} ~ {week_end_str}\n\n")

    if top_user:
        lines.append(f"本周片王: {top_user['name']}\n")
        lines.append(f"   观看时长: {sec_to_str(top_user['duration'])}\n\n")

    lines.append("电影 Top 3:\n\n")
    if movies:
        for i, r in enumerate(movies, 1):
            lines.append(f"{i}. {r['Name']}\n")
            lines.append(f"   播放次数: {r['cnt']}  时长: {sec_to_str(r['dur'])}\n")
    else:
        lines.append("该类别本周没有播放记录\n")

    lines.append("\n电视剧 Top 3:\n\n")
    if tv_shows:
        for i, r in enumerate(tv_shows, 1):
            lines.append(f"{i}. {r['Name']}\n")
            lines.append(f"   播放次数: {r['cnt']}  时长: {sec_to_str(r['dur'])}\n")
    else:
        lines.append("该类别本周没有播放记录\n")

    lines.append("\n番剧 Top 3:\n\n")
    if anime:
        for i, r in enumerate(anime, 1):
            lines.append(f"{i}. {r['Name']}\n")
            lines.append(f"   播放次数: {r['cnt']}  时长: {sec_to_str(r['dur'])}\n")
    else:
        lines.append("该类别本周没有播放记录\n")

    # 本周放送
    if calendar:
        lines.append("\n本周放送:\n\n")
        for day in calendar[:7]:
            lines.append(f"{day['date'][5:]} {day['weekday']}:\n")
            for ep in day['episodes'][:4]:
                if 'season' in ep and 'episode' in ep:
                    lines.append(f"  - {ep['name']} S{ep['season']}E{ep['episode']}\n")
                else:
                    lines.append(f"  - {ep['name']} [电影]\n")
            if len(day['episodes']) > 4:
                lines.append(f"  ... 还有 {len(day['episodes']) - 4} 部\n")
            lines.append("\n")

    lines.append(f"\n#WeekRanks  {datetime.date.today().isoformat()}")
    
    return "".join(lines)


def main():
    print("=" * 50)
    print("  Jellyfin 播放周榜生成器 V3")
    print("  (含订阅日历)")
    print("=" * 50)
    
    # 1. 确保目录存在
    ensure_dirs()
    
    # 2. 拉取数据库
    print("\n[1/5] 获取播放数据...")
    if not fetch_database():
        print("  [!] 数据库拉取失败，尝试使用缓存")
        if not os.path.exists(DB_PATH):
            print("  [X] 缓存也不存在，无法继续")
            return
    
    # 3. 统计数据
    print("\n[2/5] 统计播放榜单...")
    movies, tv_shows, anime, top_user, week_start_str, week_end_str = get_week_data()
    
    # 4. 获取订阅日历
    print("\n[3/5] 获取订阅日历...")
    calendar = get_weekly_calendar()
    
    # 5. 生成文本
    text = build_text(movies, tv_shows, anime, top_user, calendar, week_start_str, week_end_str)
    print("\n" + "=" * 50)
    print(text)
    print("=" * 50)
    
    # 6. 生成海报
    print("\n[4/5] 生成海报...")
    poster_path = get_poster_filename(week_end_str)
    draw_poster_v3(movies, tv_shows, anime, top_user, calendar, poster_path)
    
    # 7. 上传并推送
    print("\n[5/5] 上传与推送...")
    if ENABLE_PUSH:
        img_url = upload_to_lsky(poster_path)
        
        if img_url:
            desp = f"![周榜]({img_url})\n\n{text}"
            if send_serverchan(desp):
                print("  [OK] 推送成功")
            else:
                print("  [!] 推送失败")
        else:
            if send_serverchan(text):
                print("  [OK] 推送成功（无图片）")
    else:
        print("  [i] 推送已禁用（测试模式）")
        print(f"  [i] 海报位置: {poster_path}")

    print("\n" + "=" * 50)
    print("  任务完成！")
    print("=" * 50)


if __name__ == "__main__":
    main()
