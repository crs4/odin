#  Copyright (c) 2019, CRS4
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy of
#  this software and associated documentation files (the "Software"), to deal in
#  the Software without restriction, including without limitation the rights to
#  use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
#  the Software, and to permit persons to whom the Software is furnished to do so,
#  subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in all
#  copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
#  FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
#  COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
#  IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
#  CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import sys, argparse, logging
from importlib import import_module

SUBMODULES_NAMES = [
    'get_cases_scoring',
    'reviews_report',
    'extract_patches',
    'reviews_status',
]

SUBMODULES = [import_module('%s.%s' % (__package__, n)) for n in SUBMODULES_NAMES]

LOG_FORMAT = '%(asctime)s|%(levelname)-8s|%(message)s'
LOG_DATEFMT = '%Y-%m-%d %H:%M:%S'
LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


class Odin(object):

    def __init__(self):
        self.supported_submodules = []
        for m in SUBMODULES:
            m.register(self.supported_submodules)

    def make_parser(self):
        parser = argparse.ArgumentParser(description='ODIN: query tools and utilities for ProMort')
        parser.add_argument('--promort-host', type=str, required=True, help='ProMort host')
        parser.add_argument('--promort-user', type=str, required=True, help='ProMort user')
        parser.add_argument('--promort-passwd', type=str, required=True, help='ProMort password')
        parser.add_argument('--log-level', type=str, choices=LOG_LEVELS,
                            default='INFO', help='logging level (default=INFO')
        parser.add_argument('--log-file', type=str, default=None, help='log file (default=stderr)')
        subparsers = parser.add_subparsers()
        for k, h, addp, impl in self.supported_submodules:
            subparser = subparsers.add_parser(k, help=h)
            addp(subparser)
            subparser.set_defaults(func=impl)
        return parser

    def get_logger(self, log_level, log_file, mode='a'):
        logger = logging.getLogger('odin')
        if not isinstance(log_level, int):
            try:
                log_level = getattr(logging, log_level)
            except AttributeError:
                raise ValueError('Unsupported literal log level: %s' % log_level)
        logger.setLevel(log_level)
        logger.handlers = []
        if log_file:
            handler = logging.FileHandler(log_file, mode=mode)
        else:
            handler = logging.StreamHandler()
        formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger


def main(argv=None):
    app = Odin()
    parser = app.make_parser()
    args = parser.parse_args(argv)
    logger = app.get_logger(args.log_level, args.log_file)
    try:
        promort_host = args.promort_host
        user = args.promort_user
        passwd = args.promort_passwd
    except ValueError, ve:
        logger.critical(ve)
        sys.exit(ve)
    # launch proper function based on parameter passed using the command line
    args.func(promort_host, user, passwd, logger, args)
