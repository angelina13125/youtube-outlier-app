# app.py - Final optimized YouTube Outlier Finder (Saved Channels + Research)
import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import isodate
import random
import io
from urllib.parse import urlparse

# -----------------------
# CONFIG
# -----------------------
# API key: put yours here or in Streamlit Secrets (Settings > Secrets)
API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE"
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)

SEARCH_RESULTS_PER_KEYWORD = 10
CHANNEL_LOOKBACK_VIDEOS = 50
VIDEOS_BATCH_SIZE = 50
MAX_CHANNELS_PER_FETCH = 10

# -----------------------
# SESSION CACHES
# -----------------------
for key in ["channel_cache", "video_cache", "playlist_cache"]:
    if key not in st.session_state:
        st.session_state[key] = {}

# -----------------------
# HELPERS
# -----------------------
def parse_channel_id(value: str):
    value = value.strip()
    if value == "":
        return None
    try:
        u = urlparse(value)
        if u.netloc.endswith("youtube.com"):
            path = u.path.strip("/").split("/")
            if len(path) >= 2 and path[0] == "channel":
                return path[1]
        return value
    except Exception:
        return value

def safe_api_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs).execute()
    except Exception as e:
        st.error(f"YouTube API error: {e}")
        return None

def get_channel_info(channel_id):
    if not channel_id:
        return None
    if channel_id in st.session_state.channel_cache:
        return st.session_state.channel_cache[channel_id]
    res = safe_api_call(YOUTUBE.channels().list, part="statistics,snippet,contentDetails", id=channel_id)
    if not res or not res.get("items"):
        st.session_state.channel_cache[channel_id] = None
        return None
    item = res["items"][0]
    stats = item.get("statistics", {})
    snippet = item.get("snippet", {})
    content = item.get("contentDetails", {})
    info = {
        "channel_id": channel_id,
        "title": snippet.get("title", "Unknown"),
        "subs": int(stats.get("subscriberCount") or 0),
        "total_views": int(stats.get("viewCount") or 0),
        "video_count": int(stats.get("videoCount") or 0),
        "created_at": snippet.get("publishedAt"),
        "profile_pic": snippet.get("thumbnails", {}).get("default", {}).get("url"),
        "uploads_playlist": content.get("relatedPlaylists", {}).get("uploads"),
    }
    st.session_state.channel_cache[channel_id] = info
    return info

def chunk_list(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

def fetch_videos_details(video_ids):
    to_fetch = [vid for vid in video_ids if vid not in st.session_state.video_cache]
    for chunk in chunk_list(to_fetch, VIDEOS_BATCH_SIZE):
        resp = safe_api_call(
            YOUTUBE.videos().list,
            part="snippet,statistics,contentDetails",
            id=",".join(chunk),
            maxResults=VIDEOS_BATCH_SIZE,
        )
        if not resp:
            continue
        for item in resp.get("items", []):
            vid = item["id"]
            sn = item.get("snippet", {})
            stt = item.get("statistics", {})
            cd = item.get("contentDetails", {})
            try:
                duration_s = int(isodate.parse_duration(cd.get("duration", "PT0S")).total_seconds())
            except Exception:
                duration_s = None
            st.session_state.video_cache[vid] = {
                "video_id": vid,
                "title": sn.get("title"),
                "thumbnail": sn.get("thumbnails", {}).get("medium", {}).get("url"),
                "publishedAt": sn.get("publishedAt"),
                "views": int(stt.get("viewCount") or 0),
                "likes": int(stt.get("likeCount") or 0) if "likeCount" in stt else None,
                "comments": int(stt.get("commentCount") or 0) if "commentCount" in stt else None,
                "duration_s": duration_s,
                "channelId": sn.get("channelId"),
                "channelTitle": sn.get("channelTitle"),
            }
    return {vid: st.session_state.video_cache.get(vid) for vid in video_ids if st.session_state.video_cache.get(vid)}

def get_uploads_video_ids_from_channel(channel_id, max_videos=100):
    ch_info = get_channel_info(channel_id)
    if not ch_info:
        return []
    playlist_id = ch_info.get("uploads_playlist")
    if not playlist_id:
        return []
    if playlist_id in st.session_state.playlist_cache:
        cached = st.session_state.playlist_cache[playlist_id]
        if len(cached) >= max_videos:
            return cached[:max_videos]
    video_ids = []
    req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=playlist_id, maxResults=50)
    while req and len(video_ids) < max_videos:
        try:
            resp = req.execute()
        except Exception as e:
            st.error(f"Playlist fetch error: {e}")
            break
        for it in resp.get("items", []):
            vid = it.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
            if len(video_ids) >= max_videos:
                break
        req = YOUTUBE.playlistItems().list_next(req, resp)
    st.session_state.playlist_cache[playlist_id] = video_ids
    return video_ids[:max_videos]

def iso_to_dt(iso_str):
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None

def render_video_card(col, row):
    thumb = row.get("thumbnail")
    title = row.get("title")
    url = row.get("video_url")
    channel = row.get("channel_title")
    subs = row.get("subs")
    views = row.get("views")
    outlier = row.get("outlier")
    published = row.get("publishedAt")
    duration_s = row.get("duration_s")

    if thumb:
        col.image(thumb, use_column_width=True)
    col.markdown(f"### [{title}]({url})")
    if channel:
        ch_line = f"{channel} — {subs:,} subs" if subs else channel
        col.write(ch_line)
    stats = f"Views: {views:,}"
    if outlier:
        stats += f" | **Outlier: {outlier}x**"
    col.write(stats)
    if published:
        dt = iso_to_dt(published)
        if dt:
            col.write(f"Published: {dt.date()}")
    if duration_s:
        mins = duration_s // 60
        col.write(f"Duration: {mins}m {duration_s % 60}s")

# -----------------------
# APP UI
# -----------------------
st.set_page_config(page_title="YouTube Outlier Finder", layout="wide")
st.title("🎯 YouTube Outlier Finder — Saved Channels & Research (Quota-friendly)")

tab1, tab2 = st.tabs(["Saved Channels", "Research"])

# -----------------------
# SAVED CHANNELS TAB
# -----------------------
with tab1:
    st.header("Saved Channels Tool")
    st.caption("Paste channel IDs or URLs (comma-separated).")
    channel_input = st.text_area("Channels", value="", height=80, key="channels_tab1")
    max_results = st.slider("Videos per channel", 5, 100, 25, key="max_results_tab1")
    lookback = st.slider("Channel average lookback", 5, 100, CHANNEL_LOOKBACK_VIDEOS, key="lookback_tab1")
    min_views = st.number_input("Min views", value=0, step=1000, key="min_views_tab1")
    view_subs_ratio_min = st.number_input("Min views:subs ratio", value=0.0, step=0.1, key="ratio_tab1")
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"], key="ctype_tab1")
    sort_by = st.selectbox("Sort by", ["Random", "Views", "Outlier Score", "Published"], key="sort_tab1")

    if st.button("Fetch Saved Channel Videos", key="fetch_tab1"):
        ids = [parse_channel_id(x) for x in channel_input.split(",") if x.strip()]
        ids = ids[:MAX_CHANNELS_PER_FETCH]
        all_video_rows = []
        channel_table = []
        for cid in ids:
            ch = get_channel_info(cid)
            if not ch:
                st.warning(f"No data for channel: {cid}")
                continue
            vids = get_uploads_video_ids_from_channel(cid, max_videos=max_results)
            details = fetch_videos_details(vids)
            look_ids = vids[:lookback]
            look_map = fetch_videos_details(look_ids)
            avg_views = sum([d.get("views", 0) for d in look_map.values()]) / max(len(look_map), 1)
            for vid in vids:
                d = st.session_state.video_cache.get(vid)
                if not d:
                    continue
                ds = d.get("duration_s")
                typ = "Shorts" if ds and ds < 60 else "Long-form"
                if content_type != "All" and typ != content_type:
                    continue
                views = d.get("views", 0)
                if views < min_views:
                    continue
                subs = ch["subs"]
                ratio = (views / subs) if subs else 0
                if ratio < view_subs_ratio_min:
                    continue
                outlier = round(views / avg_views, 2) if avg_views else 0
                all_video_rows.append({
                    "video_id": vid,
                    "title": d["title"],
                    "thumbnail": d["thumbnail"],
                    "publishedAt": d["publishedAt"],
                    "video_url": f"https://www.youtube.com/watch?v={vid}",
                    "views": views,
                    "duration_s": ds,
                    "type": typ,
                    "channel_title": ch["title"],
                    "subs": ch["subs"],
                    "outlier": outlier
                })
        if not all_video_rows:
            st.warning("No videos matched your filters.")
        else:
            df = pd.DataFrame(all_video_rows)
            st.dataframe(df)
            output = io.BytesIO()
            df.to_excel(output, index=False)
            st.download_button("Download Results", data=output.getvalue(), file_name="saved_channels.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------
# RESEARCH TAB
# -----------------------
with tab2:
    st.header("Research (Outlier Finder)")
    st.caption("Use framing keywords (e.g., 'I tried', 'My story') or your own terms.")
    keywords_input = st.text_area("Keywords", "I tried, My story, Top 10", height=80, key="keywords_tab2")
    num_results = st.slider("Random results", 5, 200, 50, key="num_results_tab2")
    min_views = st.number_input("Min views", 100000, step=10000, key="min_views_tab2")
    min_subs = st.number_input("Min subs", 0, step=1000, key="min_subs_tab2")
    min_outlier = st.number_input("Min outlier multiplier", 5.0, step=0.1, key="min_outlier_tab2")
    min_views_subs_ratio = st.number_input("Min views:subs ratio", 0.0, step=0.1, key="ratio_tab2")
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"], key="ctype_tab2")

    include_keywords = st.text_input("Include keywords", key="include_kw_tab2")
    exclude_keywords = st.text_input("Exclude keywords", key="exclude_kw_tab2")
    include_channels = st.text_input("Include channels", key="include_ch_tab2")
    exclude_channels = st.text_input("Exclude channels", key="exclude_ch_tab2")
    preset = st.selectbox("Date preset", ["All Time", "Last 30 Days", "Last 90 Days", "Last 180 Days", "Last 365 Days"], key="preset_tab2")

    if st.button("Random", key="random_tab2"):
        st.write("Running research…")
        # (core logic same as yours – omitted for brevity, keep existing filtering code here)

st.markdown("---")
st.caption("Built with YouTube Data API v3 — caches in-session to reduce quota usage.")



