import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .library import ARTISTS, copy_library, export_m3u, plan, scan, undo


def slskd(method, endpoint, payload=None):
    base = os.environ.get('SLSKD_URL', 'http://127.0.0.1:5030').rstrip('/')
    parsed = urlparse(base)
    if parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.scheme not in ('http', 'https'):
        raise ValueError('SLSKD_URL must point to your local slskd instance')
    key = os.environ.get('SLSKD_API_KEY')
    if not key:
        raise ValueError('Set SLSKD_API_KEY to a local slskd API key')
    request = Request(base + '/api/v0/' + endpoint, method=method,
                      headers={'X-API-Key': key, 'Content-Type': 'application/json'},
                      data=json.dumps(payload).encode() if payload is not None else None)
    with urlopen(request, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else {'status': response.status}


def main():
    parser = argparse.ArgumentParser(description='Local DJ library organizer. Originals are never moved.')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('scan', help='Read audio tags and detect exact duplicates')
    p.add_argument('folder'); p.add_argument('--output', default='scan.json')
    for name in ('summary', 'plan', 'copy', 'playlist'):
        p = commands.add_parser(name)
        p.add_argument('report')
        if name in ('plan', 'copy', 'playlist'):
            p.add_argument('destination')
        if name == 'copy':
            p.add_argument('--journal', required=True)
        if name == 'playlist':
            p.add_argument('--output', required=True)
    p = commands.add_parser('undo', help='Remove unchanged copies listed in a copy journal')
    p.add_argument('journal')
    p = commands.add_parser('discover', help='Create extended-mix search links, without downloading audio')
    p.add_argument('query', nargs='?')
    p = commands.add_parser('soulseek-search', help='Start an asynchronous search in your local slskd')
    p.add_argument('query')
    p = commands.add_parser('soulseek-results')
    p.add_argument('search_id')
    p = commands.add_parser('soulseek-download', help='Queue one explicitly selected search result')
    p.add_argument('username'); p.add_argument('filename'); p.add_argument('size', type=int)
    args = parser.parse_args()
    try:
        if args.command == 'scan':
            result = scan(args.folder)
            output = Path(args.output).expanduser()
            with output.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, indent=2)
            result = {'report': str(output), 'tracks': len(result['tracks']), 'errors': result['errors']}
        elif args.command == 'undo':
            result = undo(args.journal)
        elif args.command == 'discover':
            queries = [args.query] if args.query else ARTISTS
            result = [{'query': q + ' extended mix',
                       'soundcloud': 'https://soundcloud.com/search?' + urlencode({'q': q + ' extended mix'}),
                       'spotify': 'https://open.spotify.com/search/' + quote(q + ' extended mix', safe=''),
                       'beatport': 'https://www.beatport.com/search?' + urlencode({'q': q + ' extended mix'})}
                      for q in queries]
        elif args.command == 'soulseek-search':
            result = slskd('POST', 'searches', {'searchText': args.query})
        elif args.command == 'soulseek-results':
            result = slskd('GET', 'searches/' + quote(args.search_id, safe='') + '?includeResponses=true')
        elif args.command == 'soulseek-download':
            if args.size <= 0:
                raise ValueError('File size must be positive and match the selected search result')
            result = slskd('POST', 'transfers/downloads/' + quote(args.username, safe=''),
                           [{'filename': args.filename, 'size': args.size}])
        else:
            report = json.loads(Path(args.report).read_text())
            if args.command == 'summary':
                result = {'tracks': len(report['tracks']), 'unreadable': report['errors'],
                          'exact_duplicates': sum(bool(t['duplicate_of']) for t in report['tracks']),
                          'genres': dict(Counter(t['genre'] or 'Needs genre review' for t in report['tracks'])),
                          'missing_tags': dict(Counter(k for t in report['tracks'] for k in t['needs_review'])),
                          'suggested_layout': 'Genre / Energy / 5-BPM range',
                          'note': 'Review genres and missing tags before copying. Artist names do not determine genre.'}
            elif args.command == 'plan':
                result = plan(report, args.destination)
            elif args.command == 'copy':
                result = copy_library(report, args.destination, args.journal)
            else:
                result = export_m3u(report, args.destination, args.output)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as error:
        # Never echo request headers or credentials in exception diagnostics.
        if args.command.startswith('soulseek-') and not isinstance(error, ValueError):
            print('Soulseek request failed. Check the local slskd service, API key, and API version.', file=sys.stderr)
        else:
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
