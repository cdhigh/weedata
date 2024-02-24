#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import optparse, os, shutil, sys, unittest, importlib, coverage

testDir = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(testDir, '..', 'src')))

if 1:
    TEST_MODULES = ['test_base', 'test_fields', 'test_save', 'test_queries', 'test_update', 
        'test_delete', 'test_connection']
else:
    TEST_MODULES = ['test_fields']

def runtests(suite, verbosity=1, failfast=False):
    runner = unittest.TextTestRunner(verbosity=verbosity, failfast=failfast)
    results = runner.run(suite)
    return results.failures, results.errors

def collect_tests(args=None):
    suite = unittest.TestSuite()

    if not args:
        for m in [reload_module(m) for m in TEST_MODULES]:
            module_suite = unittest.TestLoader().loadTestsFromModule(m)
            suite.addTest(module_suite)
    else:
        for arg in args:
            m = reload_module(arg)
            user_suite = unittest.TestLoader().loadTestsFromNames(m)
            suite.addTest(user_suite)

    return suite

def reload_module(module_name):
    module = importlib.import_module(module_name)
    importlib.reload(module)
    return module

if __name__ == '__main__':
    verbosity = 1 #Verbosity of output
    failfast = 1 #Exit on first failure/error
    report = '' #if debug in IDE, set to ''

    os.environ['WEEDATA_TEST_VERBOSITY'] = str(verbosity)
    os.environ['WEEDATA_SLOW_TESTS'] = '1' #Run tests that may be slow

    #os.environ['WEEDATA_TEST_BACKEND'] = 'mongodb'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'redis'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'pickle'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'datastore'

    if report:
        cov = coverage.coverage()
        cov.start()

    if not os.getenv('WEEDATA_TEST_BACKEND'):
        for env in ['datastore', 'redis', 'mongodb', 'pickle']:
            print(f'\nstarting tests for database "{env}"\n')
            os.environ['WEEDATA_TEST_BACKEND'] = env
            suite = collect_tests()
            failures, errors = runtests(suite, verbosity, failfast)
    else:
        suite = collect_tests()
        failures, errors = runtests(suite, verbosity, failfast)

    if report:
        cov.stop()
        cov.save()
        if report == 'html':
            cov.html_report(directory=os.path.join(testDir, 'covhtml'))
        else:
            cov.report()
    

    sys.exit(0)
