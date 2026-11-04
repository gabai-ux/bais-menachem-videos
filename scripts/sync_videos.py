"""Export public YouTube uploads metadata for a static GitHub Pages library."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHANNEL_ID = 'UCdYsHLHyyM8D6sLY88AZnQw'
API_KEY = os.environ.get('YOUTUBE_API_KEY')
if not API_KEY:
    raise SystemExit('Missing YOUTUBE_API_KEY GitHub Actions secret')


def api(resource, **params):
    query = urllib.parse.urlencode({**params, 'key': API_KEY})
    url = f'https://www.googleapis.com/youtube/v3/{resource}?{query}'
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=40) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if attempt == 2 or (isinstance(exc, urllib.error.HTTPError) and exc.code < 500 and exc.code != 429):
                raise RuntimeError(f'YouTube API request failed: {exc}') from exc
            time.sleep(2 ** attempt)


channel = api('channels', part='contentDetails', id=CHANNEL_ID)
items = channel.get('items', [])
if not items:
    raise SystemExit('YouTube channel not found or not accessible')
playlist_id = items[0]['contentDetails']['relatedPlaylists']['uploads']

videos = []
seen = set()
token = None
while True:
    args = dict(part='snippet', playlistId=playlist_id, maxResults=50)
    if token:
        args['pageToken'] = token
    page = api('playlistItems', **args)
    for item in page.get('items', []):
        snippet = item.get('snippet', {})
        video_id = snippet.get('resourceId', {}).get('videoId')
        title = snippet.get('title', '')
        if video_id and video_id not in seen and title not in ('Private video', 'Deleted video'):
            seen.add(video_id)
            videos.append({'id': video_id, 'title': title})
    token = page.get('nextPageToken')
    if not token:
        break

if not videos:
    raise SystemExit('No public videos found; refusing to overwrite the library with an empty list')
Path('videos.json').write_text(json.dumps(videos, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Wrote {len(videos)} videos to videos.json')
