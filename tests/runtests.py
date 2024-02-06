#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import optparse, os, shutil, sys, unittest, importlib, coverage

testDir = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(testDir, '..', 'src')))

TEST_MODULES = ['test_base', 'test_fields', 'test_save', 'test_queries', 'test_update', 'test_delete']

#report='console' | 'html'
def runtests(suite, verbosity=1, failfast=False, report=None):
    if report:
        cov = coverage.coverage()
        cov.start()
    runner = unittest.TextTestRunner(verbosity=verbosity, failfast=failfast)
    results = runner.run(suite)
    if report:
        cov.stop()
        cov.save()
        if report == 'html':
            cov.html_report(directory=os.path.join(testDir, 'covhtml'))
        else:
            cov.report()
    return results.failures, results.errors

def get_option_parser():
    usage = 'usage: %prog [-e engine_name, other options] module1, module2 ...'
    parser = optparse.OptionParser(usage=usage)
    basic = optparse.OptionGroup(parser, 'Basic test options')
    basic.add_option(
        '-e',
        '--engine',
        dest='engine',
        help=('Database engine to test, one of [datastore, mongodb]'))
    basic.add_option('-v', '--verbosity', dest='verbosity', default=1,
                     type='int', help='Verbosity of output')
    basic.add_option('-f', '--failfast', action='store_true', default=False,
                     dest='failfast', help='Exit on first failure/error.')
    basic.add_option('-s', '--slow-tests', action='store_true', default=False,
                     dest='slow_tests', help='Run tests that may be slow.')
    parser.add_option_group(basic)
    return parser

def collect_tests(args=None):
    suite = unittest.TestSuite()

    if not args:
        for m in [importlib.import_module(m) for m in TEST_MODULES]:
            module_suite = unittest.TestLoader().loadTestsFromModule(m)
            suite.addTest(module_suite)
    else:
        cleaned = ['tests.%s' % arg if not arg.startswith('tests.') else arg
                   for arg in args]
        user_suite = unittest.TestLoader().loadTestsFromNames(cleaned)
        suite.addTest(user_suite)

    return suite

if __name__ == '__main__':
    #parser = get_option_parser()
    #options, args = parser.parse_args()
    verbosity = 1 #Verbosity of output
    failfast = 0 #Exit on first failure/error
    os.environ['WEEDATA_TEST_VERBOSITY'] = str(verbosity)
    os.environ['WEEDATA_SLOW_TESTS'] = '1' #Run tests that may be slow

    os.environ['WEEDATA_TEST_BACKEND'] = 'mongodb'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'datastore'
    suite = collect_tests()
    failures, errors = runtests(suite, verbosity, failfast, report='html')

    sys.exit(0)
