"""Explicit read-only MCP smoke check; requires an endpoint and scoped credential."""
import argparse
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Full Streamable HTTP endpoint, ending in /mcp')
    parser.add_argument('--project', required=True)
    parser.add_argument('--query', required=True)
    args = parser.parse_args()
    token = os.environ.get('GIGAMIND_CLIENT_TOKEN')
    if not token:
        parser.error('Set GIGAMIND_CLIENT_TOKEN to a scoped client credential')
    async with httpx.AsyncClient(headers={'Authorization': f'Bearer {token}'}, trust_env=False) as client:
        async with streamable_http_client(args.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print('Tools:', ', '.join(sorted(tool.name for tool in tools.tools)))
                for name, arguments in [('get_identity', {}), ('search_memory', {'query': args.query, 'project_id': args.project})]:
                    result = await session.call_tool(name, arguments)
                    if result.isError:
                        raise RuntimeError(f'{name} failed; check scope and project access')
                    # Avoid printing retrieved content or credentials.
                    if name == 'get_identity':
                        print('Identity:', result.structuredContent)
                    else:
                        print('Accepted matches:', len(result.structuredContent['results']))


if __name__ == '__main__':
    asyncio.run(main())
