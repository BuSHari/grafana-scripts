# Do not edit this script. Edit configuration.py
import os
import shutil
import tarfile
import requests
import urllib.request
import geoip2.database
from datetime import datetime, timezone
from influxdb import InfluxDBClient
import configuration

current_time = datetime.now(timezone.utc).astimezone().isoformat()

payload = {'apikey': configuration.tautulli_api_key, 'cmd': 'get_activity'}

activity = requests.get('{}/api/v2'.format(configuration.tautulli_url), params=payload).json()['response']['data']

sessions = {d['session_id']: d for d in activity['sessions']}


def GeoLite2db(ipaddress):
    tar_dbfile = '{}/GeoLite2-City.tar.gz'.format(os.path.dirname(os.path.realpath(__file__)))

    dbfile = '{}/GeoLite2-City.mmdb'.format(os.path.dirname(os.path.realpath(__file__)))

    if not os.path.isfile(dbfile):
        urllib.request.urlretrieve('http://geolite.maxmind.com/download/geoip/database/GeoLite2-City.tar.gz', tar_dbfile)

        tar = tarfile.open(tar_dbfile, "r:gz")
        for files in tar.getmembers():
            if 'GeoLite2-City.mmdb' in files.name:
                files.name = os.path.basename(files.name)
                tar.extract(files, '{}/'.format(os.path.dirname(os.path.realpath(__file__))))

    reader = geoip2.database.Reader(dbfile)
    geodata = reader.city(ipaddress)

    return geodata


influx_payload = [
    {
        "measurement": "Tautulli",
        "tags": {
            "type": "stream_count"
        },
        "time": current_time,
        "fields": {
            "current_streams": int(activity['stream_count']),
            "transcode_streams": int(activity['stream_count_transcode']),
            "direct_play_streams": int(activity['stream_count_direct_play']),
            "direct_streams": int(activity['stream_count_direct_stream'])
        }
    }
]

for session in sessions.keys():
    try:
        geodata = GeoLite2db(sessions[session]['ip_address_public'])
    except ValueError:
        if configuration.tautulli_failback_ip:
            geodata = GeoLite2db(configuration.tautulli_failback_ip)
        else:
            geodata = GeoLite2db(requests.get('http://ip.42.pl/raw').text)

    latitude = geodata.location.latitude

    # Get the latitude of each session. If we cant find it then...
    if not geodata.location.latitude:
        latitude = 37.234332396
    else:
        latitude = geodata.location.latitude

    # Get the longitude of each session. If we cant find it then...
    if not geodata.location.longitude:
        longitude = -115.80666344
    else:
        longitude = geodata.location.longitude

    decision = sessions[session]['transcode_decision']

    if decision == 'copy':
        decision = 'direct stream'

    video_decision = sessions[session]['stream_video_decision']

    if video_decision == 'copy':
        video_decision = 'direct stream'

    quality = sessions[session]['stream_video_resolution']

    # If the video resolution is empty. Asssume it's an audio stream
    if not quality:
        quality = sessions[session]['container'].upper()

    elif quality in ('SD', 'sd'):
        quality = sessions[session]['stream_video_resolution'].upper()

    elif quality in '4k':
        quality = sessions[session]['stream_video_resolution'].upper()

    else:
        quality = '{}p'.format(sessions[session]['stream_video_resolution'])

    influx_payload.append(
        {
            "measurement": "Tautulli",
            "tags": {
                "type": "Session",
                "region_code": geodata.subdivisions.most_specific.iso_code,
                "latitude": latitude,
                "longitude": longitude,
                "location": '{} - {}'.format(geodata.subdivisions.most_specific.name, geodata.city.name),
                "session_key": sessions[session]['session_key']
            },
            "time": current_time,
            "fields": {
                "name": sessions[session]['friendly_name'],
                "title": sessions[session]['full_title'],
                "quality": quality,
                "video_decision": video_decision.title(),
                "transcode_decision": decision.title(),
                "platform": sessions[session]['platform'],
                "product_version": sessions[session]['product_version'],
                "quality_profile": sessions[session]['quality_profile'],
                "progress_percent": sessions[session]['progress_percent'],
                "location": geodata.city.name,
            }
        }
    )

influx = InfluxDBClient(configuration.influxdb_url, configuration.influxdb_port, configuration.influxdb_username,
                        configuration.influxdb_password, configuration.tautulli_influxdb_db_name)
influx.write_points(influx_payload)
