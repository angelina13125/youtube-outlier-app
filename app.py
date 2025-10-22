import streamlit as st
import pandas as pd
from googleapiclient.discovery import build

# ======================
# CONFIG
# ======================
st.set_page_config(page_title="YouTube Outlier Finder", layout="wide")

# ======================
# SETUP
# ======================
st.title("📈 YouTube Outlier Finder")
YOUTUBE_API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE" # add your key in Streamlit secrets
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


# ======================
# HELPER FUNCTIONS
# ======================
def get_channel_id_from_url(url):
    """Convert channel URL to channel ID"""
    try:
        if "@“ in url:
            handle = url.split("@")[-1]
            res = youtube.search().list(q=handle, type="channel", part="snippet", maxResults=1).execute()
            return res["items"][0]["snippet"]["channelId"]
        elif "channel/" in url:
            return url.split("channel/")[-1]
        else:
            return url.strip()
    except Exception:
        return None


def get_videos_from_channel(channel_id, max_results=10):
    """Fetch latest videos from a given channel ID"""
    videos = []
    try:
        req = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=max_results,
            order="date",
            type="video"
        )
        res = req.execute()
        for item in res.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            videos.append({"title": title, "video_id": video_id})
    except Exception:
        pass
    return videos


def get_video_stats(video_id):
    """Get view count and duration"""
    try:
        stats = youtube.videos().list(part="statistics,contentDetails", id=video_id).execute()
        item = stats["items"][0]
        view_count = int(item["statistics"].get("viewCount", 0))
        duration = item["contentDetails"]["duration"]
        return view_count, duration
    except Exception:
        return 0, "PT0S"


def is_long_form(duration):
    """Check if video is long form (>= 8 minutes)"""
    import isodate
    try:
        seconds = isodate.parse_duration(duration).total_seconds()
        return seconds >= 480
    except Exception:
        return False


def compute_outlier_score(view, avg):
    """Basic outlier ratio"""
    if avg == 0:
        return 0
    return round(view / avg, 2)


# ======================
# TAB 1 – SAVED CHANNELS
# ======================
tab1, tab2 = st.tabs(["Saved Channels", "Research"])

with tab1:
    st.header("Saved Channels Outlier Search")
    channels_input = st.text_area("Enter YouTube channel URLs or IDs (one per line):")
    max_videos = st.number_input("Videos per channel", 1, 50, 10)
    min_views = st.number_input("Minimum views", 0, 10_000_000, 100_000)
    only_long = st.checkbox("Only long form videos (8+ min)", True)
    sort_outlier = st.checkbox("Sort by outlier score (desc)", True)

    if st.button("Search Outlier

