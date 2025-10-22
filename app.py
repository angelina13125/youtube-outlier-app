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

YOUTUBE_API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE"  # add your key in Streamlit secrets
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


# ======================
# HELPER FUNCTIONS
# ======================
def get_channel_id_from_url(url):
    """Convert channel URL to channel ID"""
    try:
        if "@" in url:
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
   min_views = st.number_input("Minimum views", 0, 10_000_000, 100_000, key="saved_min_views")
    only_long = st.checkbox("Only long form videos (8+ min)", True)
    sort_outlier = st.checkbox("Sort by outlier score (desc)", True)

    if st.button("Search Outliers"):
        if not channels_input.strip():
            st.warning("Please enter at least one channel.")
        else:
            data = []
            for raw_url in channels_input.splitlines():
                ch_id = get_channel_id_from_url(raw_url.strip())
                if not ch_id:
                    st.error(f"No data for channel: {raw_url}")
                    continue
                vids = get_videos_from_channel(ch_id, max_videos)
                if not vids:
                    st.warning(f"No videos found for: {raw_url}")
                    continue

                view_counts = []
                for v in vids:
                    views, dur = get_video_stats(v["video_id"])
                    if views >= min_views and (not only_long or is_long_form(dur)):
                        view_counts.append(views)

                if not view_counts:
                    st.info(f"No videos matched filters for: {raw_url}")
                    continue

                avg_views = sum(view_counts) / len(view_counts)
                for v in vids:
                    views, dur = get_video_stats(v["video_id"])
                    if views >= min_views and (not only_long or is_long_form(dur)):
                        score = compute_outlier_score(views, avg_views)
                        data.append({
                            "Channel": raw_url,
                            "Title": v["title"],
                            "Views": views,
                            "Outlier Score": score,
                            "URL": f"https://www.youtube.com/watch?v={v['video_id']}"
                        })

            if not data:
                st.warning("No videos matched your filters.")
            else:
                df = pd.DataFrame(data)
                if sort_outlier:
                    df = df.sort_values(by="Outlier Score", ascending=False)
                st.dataframe(df, use_container_width=True)


# ======================
# TAB 2 – RESEARCH
# ======================
with tab2:
    st.header("Research: Explore New Niches")
    keywords = st.text_input("Enter keywords (comma-separated):")
    num_results = st.number_input("Number of random videos", 5, 50, 20)
    min_views_r = st.number_input("Minimum views", 0, 10_000_000, 100_000, key="research_min_views")
    min_outlier = st.number_input("Minimum outlier score", 1.0, 10.0, 1.0)

    if st.button("Search Research"):
        if not keywords.strip():
            st.warning("Please enter at least one keyword.")
        else:
            data = []
            for keyword in [k.strip() for k in keywords.split(",") if k.strip()]:
                res = youtube.search().list(
                    part="snippet",
                    q=keyword,
                    type="video",
                    order="viewCount",
                    maxResults=num_results
                ).execute()

                vids = res.get("items", [])
                for v in vids:
                    vid_id = v["id"]["videoId"]
                    title = v["snippet"]["title"]
                    channel = v["snippet"]["channelTitle"]
                    views, dur = get_video_stats(vid_id)
                    if views >= min_views and (not only_long or is_long_form(dur)):
                        outlier_score = compute_outlier_score(views, min_views)  # temp baseline
                        if outlier_score >= min_outlier:
                            data.append({
                                "Keyword": keyword,
                                "Channel": channel,
                                "Title": title,
                                "Views": views,
                                "Outlier Score": outlier_score,
                                "URL": f"https://www.youtube.com/watch?v={vid_id}"
                            })

            if not data:
                st.warning("No videos matched your filters.")
            else:
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True)
