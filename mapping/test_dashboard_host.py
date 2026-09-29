import unittest

from dashboard import create_parser, create_server


class DashboardHostTest(unittest.TestCase):
    def test_default_host_stays_loopback(self):
        args = create_parser().parse_args([])
        self.assertEqual('127.0.0.1', args.host)
        self.assertEqual(8766, args.port)

    def test_lan_host_and_port_are_configurable(self):
        args = create_parser().parse_args(['--host', '0.0.0.0', '--port', '8767'])
        self.assertEqual('0.0.0.0', args.host)
        self.assertEqual(8767, args.port)

    def test_server_receives_requested_bind_address(self):
        captured = {}

        class FakeServer:
            def __init__(self, address, handler):
                captured['address'] = address
                captured['handler'] = handler

        server = create_server(object(), '0.0.0.0', 8767, server_class=FakeServer)
        self.assertIsInstance(server, FakeServer)
        self.assertEqual(('0.0.0.0', 8767), captured['address'])


if __name__ == '__main__':
    unittest.main()
