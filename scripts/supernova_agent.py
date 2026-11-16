"""Small agent client. Token comes from SUPERNOVA_AGENT_TOKEN, never an argument."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(base, token, path, payload=None, method=None):
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'})) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use HTTPS (HTTP allowed only for local development), without credentials/query/fragment in the URL.')
    if not token:
        raise ValueError('SUPERNOVA_AGENT_TOKEN is required.')
    request = Request(base.rstrip('/') + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
                               'Content-Type': 'application/json'}, method=method or ('PATCH' if payload is not None else 'GET'))
    with build_opener(NoRedirects).open(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list')
    listing.add_argument('--status', choices=['draft', 'scheduled', 'published', 'failed'])
    listing.add_argument('--classification', choices=['all_green', 'news'])
    listing.add_argument('--page', type=int, default=1)
    listing.add_argument('--per-page', type=int, default=50)
    for name in ['get', 'verify', 'classify']:
        command = commands.add_parser(name)
        command.add_argument('post_id', type=int)
        if name == 'classify':
            command.add_argument('--classification', choices=['all_green', 'news'], required=True)
            command.add_argument('--reason', required=True)
            command.add_argument('--expected-version', required=True)
            command.add_argument('--request-id', required=True)
    create = commands.add_parser('create', help='Create a text post as a draft or schedule it.')
    create.add_argument('--title', required=True)
    create.add_argument('--copy', required=True)
    create.add_argument('--platform', required=True)
    create.add_argument('--hashtags', default='')
    create.add_argument('--source-type', choices=['Regular', 'News'], default='Regular')
    create.add_argument('--content-format')
    create.add_argument('--scheduled-at')
    create.add_argument('--request-id', required=True)
    edit = commands.add_parser('edit', help='Edit an unpublished post.')
    edit.add_argument('post_id', type=int)
    edit.add_argument('--expected-version', required=True)
    edit.add_argument('--request-id', required=True)
    edit.add_argument('--title')
    edit.add_argument('--copy')
    edit.add_argument('--hashtags')
    edit.add_argument('--scheduled-at')
    delete_post = commands.add_parser('delete-post', help='Delete one standalone post from Supernova.')
    delete_post.add_argument('post_id', type=int)
    delete_post.add_argument('--expected-version', required=True)
    delete_post.add_argument('--reason', required=True)
    publish = commands.add_parser('publish', help='Publish a post immediately.')
    publish.add_argument('post_id', type=int)
    publish.add_argument('--expected-version', required=True)
    publish.add_argument('--request-id', required=True)
    publish.add_argument('--reason', required=True)
    delete_article = commands.add_parser('delete-article', help='Delete one RSS article and its Supernova network versions.')
    delete_article.add_argument('article_id', type=int)
    delete_article.add_argument('--expected-title', required=True)
    delete_article.add_argument('--expected-url', required=True)
    delete_article.add_argument('--reason', required=True)
    commands.add_parser('dashboard')
    commands.add_parser('scheduled')
    commands.add_parser('version')
    args = parser.parse_args()
    token = os.environ.get('SUPERNOVA_AGENT_TOKEN', '')
    def call(path, payload=None):
        return request_json(args.base_url, token, path, payload)
    try:
        if args.command == 'list':
            query = {key: getattr(args, key) for key in ['status', 'classification', 'page', 'per_page'] if getattr(args, key) is not None}
            result = call('/api/posts?' + urlencode(query))
        elif args.command in {'get', 'verify'}:
            result = call(f'/api/posts/{args.post_id}' + ('/verify' if args.command == 'verify' else ''))
        elif args.command == 'classify':
            result = call(f'/api/posts/{args.post_id}/classification', {
                'classification': args.classification, 'reason': args.reason,
                'expected_version': args.expected_version, 'client_request_id': args.request_id})
            verified = call(f'/api/posts/{args.post_id}/verify')['post']
            result['verification_matches'] = verified['version'] == result['version'] and verified['classification'] == result['classification']
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['verification_matches'] else 2
        elif args.command == 'create':
            payload = {key: getattr(args, key) for key in ['title', 'copy', 'platform', 'hashtags', 'source_type',
                                                               'content_format', 'scheduled_at'] if getattr(args, key) is not None}
            payload['client_request_id'] = args.request_id
            result = request_json(args.base_url, token, '/api/posts', payload, method='POST')
        elif args.command == 'edit':
            payload = {key: getattr(args, key) for key in ['title', 'copy', 'hashtags', 'scheduled_at']
                       if getattr(args, key) is not None}
            if not payload:
                parser.error('edit requires at least one of --title, --copy, --hashtags, or --scheduled-at')
            payload.update(expected_version=args.expected_version, client_request_id=args.request_id)
            result = request_json(args.base_url, token, f'/api/posts/{args.post_id}', payload, method='PATCH')
        elif args.command == 'publish':
            payload = {'expected_version': args.expected_version, 'client_request_id': args.request_id,
                       'reason': args.reason}
            result = request_json(args.base_url, token, f'/api/posts/{args.post_id}/publish', payload, method='POST')
        elif args.command == 'delete-post':
            payload = {'expected_version': args.expected_version, 'reason': args.reason}
            result = request_json(args.base_url, token, f'/api/posts/{args.post_id}', payload, method='DELETE')
        elif args.command == 'delete-article':
            payload = {'expected_title': args.expected_title, 'expected_url': args.expected_url,
                       'reason': args.reason}
            result = request_json(args.base_url, token, f'/api/rss/articles/{args.article_id}/delete', payload, method='POST')
        else:
            result = call('/api/' + ('scheduled/occurrences' if args.command == 'scheduled' else args.command))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HTTPError as error:
        print(json.dumps({'error': 'http_error', 'status': error.code}), file=sys.stderr)
    except (URLError, TimeoutError, ValueError):
        print(json.dumps({'error': 'request_failed', 'hint': 'Check URL, token and connectivity. After an uncertain PATCH, retry with the same request ID and payload.'}), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
