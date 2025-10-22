# app.py - Optimized YouTube Research Finder
import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime
import isodate
import random
from urllib.parse import urlparse

# -----------------------
# CONFIG
# -----------------------

API_KEY = st.secrets["youtube_api_key"]

YOUTUBE = build("youtube", "v3", developerKey=API_KEY)
SEARCH_RESULTS_PER_KEYWORD = 10  # number of videos fetched per keyword

# -----------------------
# SESSION CACHES
# -----------------------
if "video_cache" not in st.session_state:
    st.session_state.video_cache = {}  # video_id -> info dict
if "channel_cache" not in st.session_state:
    st.session_state.channel_cache = {}  # channel_id -> info dict

# -----------------------
# HELPERS
# -----------------------
def safe_api_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs).execute()
    except Exception as e:
        st.warning(f"YouTube API error: {e}")
        return None

def get_channel_info(channel_id):
    if channel_id in st.session_state.channel_cache:
        return st.session_state.channel_cache[channel_id]
    res = safe_api_call(
        YOUTUBE.channels().list,
        part="statistics,snippet,contentDetails",
        id=channel_id,
        fields="items(id,snippet(title),statistics(subscriberCount,viewCount,videoCount),contentDetails(relatedPlaylists(uploads)))"
    )
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
        resp = safe_api_call(
            YOUTUBE.videos().list,
            part="snippet,statistics,contentDetails",
            id=",".join(chunk),
            fields="items(id,snippet(title,channelId,channelTitle,publishedAt,thumbnails),statistics(viewCount),contentDetails(duration))"
        )
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

def iso_to_dt(iso_str):
    try:
        return datetime.fromisoformat(iso_str.replace("Z","+00:00"))
    except:
        return None

def render_video_card(col, row):
    if row.get("thumbnail"):
        col.image(row["thumbnail"], use_container_width=True)
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
st.set_page_config(page_title="YouTube Research Finder", layout="wide")
st.title("🎯 YouTube Research Finder")

st.header("Research")
keywords_input = st.text_area("Keywords (comma separated)")
num_results = st.slider("Number of random results", 5, 50, 20)
content_type = st.selectbox("Content type", ["All","Long-form","Shorts"])
min_outlier = st.number_input("Min outlier multiplier", value=1.0, step=0.1)

if st.button("Fetch Research Videos"):
    keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
    candidate_vids = []

    # ----------------------- SEARCH VIDEOS -----------------------
    with st.spinner("Searching videos..."):
        for kw in keywords:
            res = safe_api_call(
                YOUTUBE.search().list,
                part="id",
                q=kw,
                type="video",
                maxResults=SEARCH_RESULTS_PER_KEYWORD,
                order="viewCount"
            )
            if not res:
                continue
            candidate_vids.extend([it["id"]["videoId"] for it in res.get("items",[])])
    candidate_vids = list(dict.fromkeys(candidate_vids))  # remove duplicates

    # ----------------------- FETCH VIDEO DETAILS -----------------------
    fetch_videos_details(candidate_vids)

    # ----------------------- FETCH CHANNEL INFO -----------------------
    final_rows = []
    channel_cache = {}
    for vid in candidate_vids:
        vid_data = st.session_state.video_cache.get(vid)
        if not vid_data:
            continue
        ch_id = vid_data["channelId"]
        if ch_id not in channel_cache:
            channel_cache[ch_id] = get_channel_info(ch_id)
        ch = channel_cache[ch_id]
        if not ch:
            continue
        avg_views = ch["total_views"]/max(ch["video_count"],1)
        views = vid_data["views"]
        outlier = round(views/avg_views,2) if avg_views else 0
        typ = "Shorts" if vid_data.get("duration_s") and vid_data["duration_s"]<60 else "Long-form"
        if content_type!="All" and typ!=content_type:
            continue
        if outlier < min_outlier:
            continue
        final_rows.append({
            "video_id": vid,
            "title": vid_data["title"],
            "video_url": f"https://www.youtube.com/watch?v={vid}",
            "views": views,
            "outlier": outlier,
            "channel_title": ch["title"],
            "subs": ch["subs"],
            "publishedAt": vid_data.get("publishedAt"),
            "duration_s": vid_data.get("duration_s"),
            "thumbnail": vid_data.get("thumbnail")
        })

    # ----------------------- DISPLAY RESULTS -----------------------
    if not final_rows:
        st.warning("No videos matched filters.")
    else:
        final_sample = random.sample(final_rows, min(num_results, len(final_rows)))
        st.subheader(f"Research Results ({len(final_sample)})")
        for i in range(0,len(final_sample),4):
            cols = st.columns(4)
            for j,col in enumerate(cols):
                idx = i+j
                if idx < len(final_sample):
                    render_video_card(col, final_sample[idx])
