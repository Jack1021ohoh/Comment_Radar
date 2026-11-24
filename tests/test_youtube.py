import pytest

from radar_mcp.youtube import video_id_from_url


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "dQw4w9WgXcQ",
])
def test_video_ids(url):
    assert video_id_from_url(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    "", "https://bsky.app/profile/x/post/y", "https://www.youtube.com/@somechannel",
    "https://evil.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=short",
])
def test_not_videos(url):
    assert video_id_from_url(url) is None
