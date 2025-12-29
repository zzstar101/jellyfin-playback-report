#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jellyfin 剧集分类分析工具

用于分析 Jellyfin 媒体库中剧集的 ParentId，
帮助配置 weekly_rank_v2.py 中的 LIBRARY_ANIME 和 LIBRARY_TV。

使用方法：
1. 配置 JELLYFIN_URL 和 JELLYFIN_API_KEY
2. 修改 known_anime 和 known_tv 列表，添加你知道分类的剧集名称
3. 运行脚本，查看输出的 ParentId
4. 将相同 ParentId 的剧集对应的 ID 配置到 weekly_rank_v2.py
"""
import requests
import json

# ============ 配置区 ============
JELLYFIN_URL = "https://your-jellyfin-server.com"
JELLYFIN_API_KEY = "YOUR_JELLYFIN_API_KEY"

# 已知的分类（用于分析 ParentId）
# 添加一些你确定分类的剧集名称
known_anime = ["你的番剧1", "你的番剧2"]
known_tv = ["你的电视剧1", "你的电视剧2"]
# ================================

all_series = known_anime + known_tv

print("=" * 60)
print("Jellyfin 剧集 ParentId 分析工具")
print("=" * 60)
print("\n此工具用于获取剧集的 ParentId，帮助配置分类逻辑。")
print("相同媒体库的剧集会有相同的 ParentId。\n")

for series_name in all_series:
    print(f"【{series_name}】")
    
    try:
        url = f"{JELLYFIN_URL}/Items"
        params = {
            "searchTerm": series_name,
            "Limit": 1,
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Fields": "ParentId,Path"
        }
        headers = {"X-Emby-Token": JELLYFIN_API_KEY}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        
        if r.status_code == 200 and r.json().get("Items"):
            item = r.json()["Items"][0]
            parent_id = item.get("ParentId", "N/A")
            path = item.get("Path", "N/A")
            
            print(f"  ParentId: {parent_id}")
            print(f"  Path: {path}")
            print()
        else:
            print(f"  未找到\n")
    except Exception as e:
        print(f"  错误: {e}\n")

print("=" * 60)
print("\n使用说明：")
print("1. 番剧的 ParentId 应该相同 → 填入 LIBRARY_ANIME")
print("2. 电视剧的 ParentId 应该相同 → 填入 LIBRARY_TV")
print("3. 将这些 ID 配置到 weekly_rank_v2.py 中即可")
print("=" * 60)
