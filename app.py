# app.py - Simplified YouTube Outlier Finder
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
API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE"
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)
MAX_VIDEOS_PER_CHANNEL = 50
SEARCH_RESULTS_PER_KEYWORD = 10

# -----------------------
# SESSION CACHES
# -----------------------
if "channel_cache" not in st.session_state:
    st.session_state.channel_cache = {}   # channel_id -> info dict
if "video_cache" not in st.session_state:
    st.session_state.video_cache = {}     # video_id -> info dict

# -----------------------
# HELPERS
# -----------------------
def parse_channel_id(value: str):
    """Resolve /channel/ URLs, @handles, or raw IDs"""
    value = value.strip()
    if not value:
        return None
    try:
        u = urlparse(value)
        if u.netloc.endswith("youtube.com"):
            path = u.path.strip("/").split("/")
            if len(path) >= 2 and path[0] == "channel":
                return path[1]
            elif path[0].startswith("@"):
                # search handle
                res = YOUTUBE.search().list(part="snippet", q=path[0], type="channel", maxResults=1).execute()
                items = res.get("items", [])
                if items:
                    return items[0]["snippet"]["channelId"]
        return value
    except Exception:
        return value

def safe_api_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs).execute()
    except Exception as e:
        st.warning(f"YouTube API error: {e}")
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
        "uploads_playlist": content.get("relatedPlaylists", {}).get("uploads")
    }
    st.session_state.channel_cache[channel_id] = info
    return info

def fetch_videos_details(video_ids):
    to_fetch = [vid for vid in video_ids if vid not in st.session_state.video_cache]
    for i in range(0, len(to_fetch), 50):
        chunk = to_fetch[i:i+50]
        resp = safe_api_call(YOUTUBE.videos().list, part="snippet,statistics,contentDetails", id=",".join(chunk))
        if not resp:
            continue
        for item in resp.get("items", []):
            vid = item["id"]
            sn = item.get("snippet", {})
            stt = item.get("statistics", {})
            cd = item.get("contentDetails", {})
            try:
                duration_s = int(isodate.parse_duration(cd.get("duration","PT0S")).total_seconds())
            except:
                duration_s = None
            st.session_state.video_cache[vid] = {
                "video_id": vid,
                "title": sn.get("title"),
                "channelId": sn.get("channelId"),
                "channelTitle": sn.get("channelTitle"),
                "views": int(stt.get("viewCount") or 0),
                "publishedAt": sn.get("publishedAt"),
                "duration_s": duration_s,
                "thumbnail": sn.get("thumbnails", {}).get("medium", {}).get("url")
            }
    return {vid: st.session_state.video_cache[vid] for vid in video_ids if vid in st.session_state.video_cache}

def get_channel_video_ids(channel_id, max_videos=MAX_VIDEOS_PER_CHANNEL):
    ch_info = get_channel_info(channel_id)
    if not ch_info or not ch_info.get("uploads_playlist"):
        return []
    playlist_id = ch_info["uploads_playlist"]
    video_ids = []
    req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=playlist_id, maxResults=50)
    while req and len(video_ids) < max_videos:
        try:
            resp = req.execute()
        except:
            break
        for it in resp.get("items", []):
            vid = it["contentDetails"]["videoId"]
            video_ids.append(vid)
            if len(video_ids) >= max_videos:
                break
        req = YOUTUBE.playlistItems().list_next(req, resp)
    return video_ids[:max_videos]

def iso_to_dt(iso_str):
    try:
        return datetime.fromisoformat(iso_str.replace("Z","+00:00"))
    except:
        return None

def render_video_card(col, row):
    if row.get("thumbnail"):
        col.image(row["thumbnail"], use_column_width=True)
    col.markdown(f"### [{row['title']}]({row['video_url']})")
    col.write(f"{row['channel_title']} — {int(row['subs']):,} subs")
    col.write(f"Views: {int(row['views']):,}")
    col.markdown(f"<span style='color:green;font-weight:700'>Outlier: {row['outlier']}x</span>", unsafe_allow_html=True)
    dt = iso_to_dt(row.get("publishedAt"))
    if dt:
        col.write(f"Published: {dt.date()}")
    if row.get("duration_s"):
        mins = row['duration_s']//60
        col.write(f"Duration: {mins}m {row['duration_s']%60}s")

# -----------------------
# APP UI
# -----------------------
st.set_page_config(page_title="YouTube Outlier Finder", layout="wide")
st.title("🎯 YouTube Outlier Finder")

tab1, tab2 = st.tabs(["Saved Channels", "Research"])

# -----------------------
# SAVED CHANNELS
# -----------------------
with tab1:
    st.header("Saved Channels")
    channel_input = st.text_area("Channel IDs or URLs (comma separated)")
    max_videos = st.slider("Videos per channel", 5, 50, 10)
    min_views = st.number_input("Min views", value=0, step=1000)
    view_subs_ratio_min = st.number_input("Min views/subs ratio", value=0.0, step=0.1)
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"])
    sort_by = st.selectbox("Sort by", ["Random","Views","Outlier"])
    
    if st.button("Fetch Saved Channel Videos"):
        all_rows = []
        for cid_raw in channel_input.split(","):
            cid = parse_channel_id(cid_raw)
            ch = get_channel_info(cid)
            if not ch:
                st.warning(f"No data for channel: {cid_raw}")
                continue
            vids = get_channel_video_ids(cid, max_videos=max_videos)
            fetch_videos_details(vids)
            avg_views = ch["total_views"] / max(ch["video_count"],1)
            for vid in vids:
                d = st.session_state.video_cache.get(vid)
                if not d:
                    continue
                typ = "Shorts" if d.get("duration_s") and d["duration_s"]<60 else "Long-form"
                if content_type != "All" and typ != content_type:
                    continue
                views = d["views"]
                if views < min_views:
                    continue
                ratio = (views / ch["subs"]) if ch["subs"] else float('inf')
                if ratio < view_subs_ratio_min:
                    continue
                all_rows.append({
                    "video_id": vid,
                    "title": d["title"],
                    "video_url": f"https://www.youtube.com/watch?v={vid}",
                    "views": views,
                    "outlier": round(views/avg_views,2) if avg_views else 0,
                    "channel_title": ch["title"],
                    "subs": ch["subs"],
                    "publishedAt": d.get("publishedAt"),
                    "duration_s": d.get("duration_s"),
                    "thumbnail": d.get("thumbnail")
                })
        if not all_rows:
            st.warning("No videos matched filters.")
        else:
            df = pd.DataFrame(all_rows)
            if sort_by=="Views":
                df = df.sort_values("views", ascending=False)
            elif sort_by=="Outlier":
                df = df.sort_values("outlier", ascending=False)
            elif sort_by=="Random":
                df = df.sample(frac=1)
            st.subheader(f"Videos ({len(df)})")
            for i in range(0,len(df),4):
                cols = st.columns(4)
                for j,col in enumerate(cols):
                    idx = i+j
                    if idx < len(df):
                        render_video_card(col, df.iloc[idx])
            # download
            output = io.BytesIO()
            df.to_excel(output,index=False)
            st.download_button("Download results", data=output.getvalue(), file_name="saved_channels.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------
# RESEARCH
# -----------------------
with tab2:
    st.header("Research")
    keywords_input = st.text_area("Keywords (comma separated)")
    num_results = st.slider("Number of random results", 5, 50, 20)
    min_views = st.number_input("Min views", value=0, step=1000, key="r_min_views")
    min_subs = st.number_input("Min channel subscribers", value=0, step=1000)
    min_outlier = st.number_input("Min outlier multiplier", value=1.0, step=0.1)
    content_type = st.selectbox("Content type", ["All","Long-form","Shorts"], key="r_content_type")

    if st.button("Fetch Research Videos"):
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
        candidate_vids = []
        with st.spinner("Searching videos..."):
            for kw in keywords:
                res = safe_api_call(YOUTUBE.search().list, part="id", q=kw, type="video", maxResults=SEARCH_RESULTS_PER_KEYWORD, order="viewCount")
                if not res:
                    continue
                candidate_vids.extend([it["id"]["videoId"] for it in res.get("items",[])])
        candidate_vids = list(dict.fromkeys(candidate_vids))
        fetch_videos_details(candidate_vids)
        final_rows = []
        for vid in candidate_vids:
            d = st.session_state.video_cache.get(vid)
            if not d:
                continue
            ch = get_channel_info(d["channelId"])
            if not ch:
                continue
            avg_views = ch["total_views"]/max(ch["video_count"],1)
            views = d["views"]
            outlier = round(views/avg_views,2) if avg_views else 0
            typ = "Shorts" if d.get("duration_s") and d["duration_s"]<60 else "Long-form"
            if content_type!="All" and typ!=content_type:
                continue
            if views < min_views or ch["subs"]<min_subs or outlier<min_outlier:
                continue
            final_rows.append({
                "video_id": vid,
                "title": d["title"],
                "video_url": f"https://www.youtube.com/watch?v={vid}",
                "views": views,
                "outlier": outlier,
                "channel_title": ch["title"],
                "subs": ch["subs"],
                "publishedAt": d.get("publishedAt"),
                "duration_s": d.get("duration_s"),
                "thumbnail": d.get("thumbnail")
            })
        if not final_rows:
            st.warning("No videos matched filters.")
        else:
            final_sample = random.sample(final_rows, min(num_results, len(final_rows)))
            df = pd.DataFrame(final_sample)
            st.subheader(f"Research Results ({len(df)})")
            for i in range(0,len(df),4):
                cols = st.columns(4)
                for j,col in enumerate(cols):
                    idx = i+j
                    if idx < len(df):
                        render_video_card(col, df.iloc[idx])
            # download
            output = io.BytesIO()
            df.to_excel(output,index=False)
            st.download_button("Download results", data=output.getvalue(), file_name="research.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")







