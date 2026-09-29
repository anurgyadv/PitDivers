"""Explicit per-command duty for the legacy direction names."""
from urllib.request import Request


def manual_request(rover, direction, duty=None):
    signs = {'forward': (1, 1), 'backward': (-1, -1),
             'left': (-1, 1), 'right': (1, -1), 'stop': (0, 0)}
    if direction not in signs:
        raise ValueError('Invalid direction')
    if duty is not None and (isinstance(duty, bool) or not isinstance(duty, int)
                             or not 80 <= duty <= 255):
        raise ValueError('Motor duty must be an integer from 80 to 255')
    if direction == 'stop' or duty is None:
        return Request(rover + '/' + direction)
    a, b = signs[direction]
    return Request(f'{rover}/api/wheels?a={a*duty}&b={b*duty}', data=b'', method='POST')
