import functools
from typing import List, Optional, TypedDict, cast

import m3u8
import m3u8.mixins
from ttml2ssa import Ttml2Ssa
import requests
import sys
import os
import shutil
from urllib.parse import urlencode, parse_qsl
import xbmcgui
import xbmcvfs
import xbmcplugin
import xbmcaddon
import xbmc

from piped.types import Stream, StreamResponse, StreamSubtitle


_HANDLE = int(sys.argv[1])
addon_id = 'plugin.video.youtube'
selfAddon = xbmcaddon.Addon(id=addon_id)
#datapath = xbmc.translatePath(selfAddon.getAddonInfo('profile')).decode('utf-8')
#addonfolder = xbmc.translatePath(selfAddon.getAddonInfo('path')).decode('utf-8')
value_1 = selfAddon.getSettingString('piped.instance')
tmp_dir = xbmcvfs.translatePath('special://temp')

def get_subtitle_from_piped(subtitle: Optional[StreamSubtitle], frame_rate: float) -> Optional[str]:
    if subtitle is None:
        return None

    response = requests.get(subtitle['url'], headers={'Accept': 'text/xml;*/*'})
    if response.status_code < 200 or response.status_code >= 300:
        return None

    try:
        ttml = Ttml2Ssa(source_fps=frame_rate)

        ttml.parse_ttml_from_string(response.text)
        path = os.path.join(tmp_dir, "piped-subtitles.srt")
        ttml.write2file(path)
        return path
    except Exception:
        return None


def get_playlist_ready(
        playlist_ref: m3u8.mixins.BasePathMixin,
        base_url: str,
        hls_path: str,
        base_dir,
):
    """
    Downloads and saves the m3u8 playlist, updating all segments to have absolute urls, also updates the resources
    uri to point to the downloaded file
    
    Mutates playlist_ref!
    """
    resolved_url = f"{base_url}/{playlist_ref.uri}"
    playlist = m3u8.load(resolved_url)

    for s in playlist.segments:
        segment = cast(m3u8.Segment, s)
        segment.base_path = f"{base_url}{segment.base_path}"
    
    with open(f"{base_dir}/{hls_path}", "w") as file:
        # There seems to be a bug in m3u8 and it's impossible to update the EXT-X-MAP
        # URI. For now, this really does seem to be the easiest way to add the base_url to the uri
        file.write(
            playlist.dumps().replace('URI="/', f'URI="{base_url}/')
        )

    # ordering matters here apparently, also these 3 are all necessary
    playlist_ref.uri = hls_path
    playlist_ref.base_path = ''
    playlist_ref.uri = hls_path

    return hls_path


def play_video(path):
    instance = value_1
    response = requests.get(f'https://{instance}/streams/{path}')
    piped_response: StreamResponse = response.json()

    master_playlist = m3u8.load(piped_response['hls'])

    class Acc(TypedDict, total=False):
        res_0: int
        fps: int
        playlist: m3u8.Playlist
        bandwidth: int

    def playlist_reducer(acc: Acc, playlist: m3u8.Playlist) -> Acc:
        stream_info = playlist.stream_info
        if stream_info is None:
            return acc

        if stream_info.resolution is None or not playlist.uri:
            return acc

        resolution: tuple[int, int] = stream_info.resolution
        frame_rate = stream_info.frame_rate if int(stream_info.frame_rate) is not None else 1

        if resolution[0] > 1920 or resolution[0] < acc["res_0"]:
            return acc

        if frame_rate < acc["fps"]:
            return acc

        if stream_info.bandwidth < acc["bandwidth"]:
            return acc

        return {"fps": frame_rate, "res_0": resolution[0], "playlist": playlist, "bandwidth": stream_info.bandwidth}

    [protocol, _, domain, *__] = piped_response['hls'].split('/')

    base_url = f"{protocol}//{domain}"
    base_dir = os.path.join(tmp_dir, "piped/hls-manifests")

    shutil.rmtree(base_dir, ignore_errors=True)
    os.makedirs(base_dir)

    video_playlist = functools.reduce(playlist_reducer, list(master_playlist.playlists), {"res_0": 0, "fps": 0, "bandwidth": 0})["playlist"]
    new_master_playlist = m3u8.M3U8()

    audio_id: str = video_playlist.stream_info.audio

    audio_playlists: List[m3u8.Media] = [m for m in master_playlist.media if m.group_id == audio_id and 'en' in (m.language or 'en')]

    get_playlist_ready(video_playlist, base_url=base_url, base_dir=base_dir, hls_path="video-index.m3u8")
    video_playlist.stream_info.subtitles = 'NONE'
    for audio_playlist in audio_playlists:
        audio_path = xbmcvfs.makeLegalFilename(f"{audio_playlist.language}-audio-index.m3u8").lstrip('/').rstrip('/')
        get_playlist_ready(audio_playlist, base_url=base_url, base_dir=base_dir, hls_path=audio_path)
        audio_playlist

    new_master_playlist.add_playlist(video_playlist)
    new_master_playlist.add_media(audio_playlist)

    new_master_playlist.is_independent_segments = True
    new_master_playlist.data["is_independent_segments"] = True
    hls_path = f"{base_dir}/index.m3u8"
    new_master_playlist.dump(hls_path)

    subtitle = next(
        (subtitle for subtitle in piped_response['subtitles'] if 'en' in subtitle['code'] and subtitle['autoGenerated'] is False),
        None
    )

    list_item = xbmcgui.ListItem(
        label=piped_response["title"],
        label2=piped_response["uploader"],
        path=hls_path,
    )
    list_item.setMimeType('application/x-mpegURL')
    list_item.setContentLookup(False)
    list_item.setProperty("inputstream", "inputstream.ffmpegdirect")
    list_item.setProperty("inputstream.ffmpegdirect.is_realtime_stream", "false")
    list_item.setProperty("inputstream.ffmpegdirect.manifest_type", "hls")
    list_item.setProperty("inputstream.ffmpegdirect.open_mode", "ffmpeg")

    subtitle_path = get_subtitle_from_piped(subtitle, video_playlist.stream_info.frame_rate)
    if subtitle_path is not None:
        list_item.setSubtitles([subtitle_path])

    list_item.setArt({
        "thumb": piped_response["thumbnailUrl"]
    })

    def send_notification(method, data):
        xbmc.executebuiltin('NotifyAll(plugin.video.youtube,%s,%s)' % (method, data))

    send_notification('PlaybackInit', {
        'video_id': path,
        #'channel_id': playback_json.get('channel_id', ''),
        #'status': playback_json.get('video_status', {})
    })
    xbmcplugin.setResolvedUrl(handle=_HANDLE, succeeded=True, listitem=list_item)


def router(paramstring, action = None):
    """
    Handle command data sent from Kodi
    """
    params = dict(parse_qsl(paramstring))
    if action:
        if action == 'play':
            play_video(params['video_id'])
        # If this add-on is registered as plugin.video.youtube, below will
        # handle NewPipe's "Play with Kodi" action. Makes it easy to share
        # video URLs from a phone
        elif action == "/play/":
            video_id = paramstring.split('=', 1)[1] # /play/?videoid=...
            if video_id:
                play_video(video_id)
        #     else:
        #         raise ValueError('Invalid paramstring: {}!'.format(paramstring))
        # else:
        #     raise ValueError('Invalid action: {}' % action)

if __name__ == '__main__':
    [*_, action] = [segment for segment in sys.argv[0].split('/') if segment != '']
    router(sys.argv[2][1:], action)
