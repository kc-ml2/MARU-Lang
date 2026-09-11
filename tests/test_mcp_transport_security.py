import unittest
from types import SimpleNamespace

from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request

from maru_lang.mcp_server import create_mcp_server


class TransportSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, public_url, host, origin=None):
        server = create_mcp_server(SimpleNamespace(
            settings=SimpleNamespace(public_url=public_url)))
        settings = server.settings.transport_security
        self.assertTrue(settings.enable_dns_rebinding_protection)
        headers = [(b'host', host.encode()), (b'content-type', b'application/json')]
        if origin:
            headers.append((b'origin', origin.encode()))
        request = Request({'type': 'http', 'method': 'POST', 'path': '/mcp',
                           'headers': headers})
        return await TransportSecurityMiddleware(settings).validate_request(request, is_post=True)

    async def test_public_domain_and_default_port(self):
        for host in ['maru.ml2-alpha.com', 'maru.ml2-alpha.com:443']:
            self.assertIsNone(await self.check('https://maru.ml2-alpha.com', host,
                                              'https://maru.ml2-alpha.com'))

    async def test_local_access_remains_available(self):
        for host in ['localhost:8001', '127.0.0.1:8001', '[::1]:8001']:
            self.assertIsNone(await self.check('https://maru.ml2-alpha.com', host))

    async def test_untrusted_host_and_origin_rejected(self):
        for host in ['evil.example', 'maru.ml2-alpha.com.evil.example', 'maru.ml2-alpha.com:8080']:
            response = await self.check('https://maru.ml2-alpha.com', host)
            self.assertEqual(response.status_code, 421)
        response = await self.check('https://maru.ml2-alpha.com', 'maru.ml2-alpha.com',
                                    'https://evil.example')
        self.assertEqual(response.status_code, 403)

    async def test_explicit_port_and_ipv6(self):
        self.assertIsNone(await self.check('https://maru.example:8443/base',
                                          'maru.example:8443', 'https://maru.example:8443'))
        self.assertIsNone(await self.check('https://[2001:db8::1]:8443',
                                          '[2001:db8::1]:8443', 'https://[2001:db8::1]:8443'))
