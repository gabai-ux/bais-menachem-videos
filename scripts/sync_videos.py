"""Export public YouTube uploads, applying private Google Sheets admin overrides."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHANNEL_ID = 'UCdYsHLHyyM8D6sLY88AZnQw'
API_KEY = os.environ.get('YOUTUBE_API_KEY')
ADMIN_SHEET_URL = os.environ.get('ADMIN_SHEET_URL')
ADMIN_SYNC_TOKEN = os.environ.get('ADMIN_SYNC_TOKEN')

if not API_KEY:
    raise SystemExit('Missing YOUTUBE_API_KEY GitHub Actions secret')
if not ADMIN_SHEET_URL or not ADMIN_SYNC_TOKEN:
    raise SystemExit('Missing ADMIN_SHEET_URL or ADMIN_SYNC_TOKEN GitHub Actions secret')


def get_json(url, label):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=40) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2 or (isinstance(exc, urllib.error.HTTPError) and exc.code < 500 and exc.code != 429):
                raise RuntimeError(f'{label} request failed: {type(exc).__name__}') from exc
            time.sleep(2 ** attempt)


def api(resource, **params):
    query = urllib.parse.urlencode({**params, 'key': API_KEY})
    return get_json(f'https://www.googleapis.com/youtube/v3/{resource}?{query}', 'YouTube API')


def get_admin_overrides():
    parsed = urllib.parse.urlsplit(ADMIN_SHEET_URL)
    if parsed.scheme != 'https' or parsed.hostname != 'script.google.com' or not parsed.path.endswith('/exec'):
        raise RuntimeError('ADMIN_SHEET_URL must be an HTTPS Google Apps Script /exec URL')
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(('token', ADMIN_SYNC_TOKEN))
    url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    data = get_json(url, 'Admin Sheet')
    if isinstance(data, dict) and 'error' in data:
        raise RuntimeError('Admin Sheet rejected the request; check the deployment and token')
    if not isinstance(data, list):
        raise RuntimeError('Admin Sheet response is not a list; refusing to overwrite videos.json')
    overrides = {}
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            raise RuntimeError('Invalid admin row; expected an object with a video ID')
        video_id = item['id'].strip()
        if len(video_id) != 11 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in video_id):
            raise RuntimeError('Invalid YouTube video ID in Admin Sheet')
        if video_id in overrides:
            raise RuntimeError(f'Duplicate video ID in Admin Sheet: {video_id}')
        for field in ('speaker', 'series', 'title'):
            if field in item and not isinstance(item[field], str):
                raise RuntimeError(f'Invalid {field} for video {video_id}')
        if 'hidden' in item and not isinstance(item['hidden'], bool):
            raise RuntimeError(f'Invalid hidden value for video {video_id}')
        overrides[video_id] = item
    return overrides


def main():
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

    overrides = get_admin_overrides()
    output = []
    hidden_count = 0
    applied_count = 0
    for video in videos:
        correction = overrides.get(video['id'])
        if correction:
            if correction.get('hidden') is True:
                hidden_count += 1
                continue
            for field in ('speaker', 'series'):
                if field in correction:
                    video[field] = correction[field]
            if 'title' in correction:
                video['originalTitle'] = video['title']
                video['title'] = correction['title']
            applied_count += 1
        output.append(video)

    if not output:
        raise SystemExit('All videos are hidden; refusing to overwrite the library with an empty list')
    Path('videos.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {len(output)} videos to videos.json; applied {applied_count} admin rows; hidden {hidden_count}')


if __name__ == '__main__':
    main()
