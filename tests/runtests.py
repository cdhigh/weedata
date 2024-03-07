#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import re, os, shutil, sys, unittest, importlib, coverage

testDir = os.path.dirname(__file__)
weedataDir = os.path.abspath(os.path.join(testDir, '..', 'src'))
sys.path.insert(0, weedataDir)

def runtests(suite, verbosity=1, failfast=False):
    runner = unittest.TextTestRunner(verbosity=verbosity, failfast=failfast)
    results = runner.run(suite)
    return results.failures, results.errors

def collect_tests(module=None):
    suite = unittest.TestSuite()
    modules = [module] if module else TEST_MODULES
    for target in modules:
        m = reload_module(target)
        user_suite = unittest.TestLoader().loadTestsFromModule(m)
        suite.addTest(user_suite)
    return suite

def reload_module(module_name):
    module = importlib.import_module(module_name)
    importlib.reload(module)
    return module

class DatastoreMocker:
    def __init__(self, backEnd):
        self.backEnd = backEnd
    def mock(self, act):
        pklFile = os.path.join(testDir, 'fake_datastore.pkl')
        if os.path.exists(pklFile):
            os.remove(pklFile)

        clientPy = os.path.join(weedataDir, 'weedata', 'client.py')
        with open(clientPy, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

        newLines = lines[:]
        for idx in range(50):
            if act == 'mock':
                if newLines[idx] == "#if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':":
                    newLines[idx] = "if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':"
                if newLines[idx] == "#    from fake_datastore import *":
                    newLines[idx] = "    from fake_datastore import *"
                if newLines[idx] == "#    print('Alert: using fake datastore stub!!!')":
                    newLines[idx] = "    print('Alert: using fake datastore stub!!!')"
            elif act == 'unmock':
                if newLines[idx] == "if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':":
                    newLines[idx] = "#if os.environ.get('WEEDATA_TEST_BACKEND') == 'datastore':"
                if newLines[idx] == "    from fake_datastore import *":
                    newLines[idx] = "#    from fake_datastore import *"
                if newLines[idx] == "    print('Alert: using fake datastore stub!!!')":
                    newLines[idx] = "#    print('Alert: using fake datastore stub!!!')"

        if newLines != lines:
            print(f'module datastore {act}ed.')
            with open(clientPy, 'w', encoding='utf-8') as f:
                f.write('\n'.join(newLines))

    def __enter__(self):
        if self.backEnd == 'datastore':
            self.mock('mock')
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.backEnd == 'datastore':
            self.mock('unmock')

def start_test(verbosity=1, failfast=0, testonly='', report=''):
    if report:
        cov = coverage.coverage()
        cov.start()

    envs = os.getenv('WEEDATA_TEST_BACKEND')
    envs = [envs] if envs else ['datastore', 'redis', 'mongodb', 'pickle']
    for env in envs:
        print(f'starting tests for database "{env}"')
        os.environ['WEEDATA_TEST_BACKEND'] = env
        with DatastoreMocker(env):
            runtests(collect_tests(testonly), verbosity, failfast)
        
    if report:
        cov.stop()
        cov.save()
        if report == 'html':
            cov.html_report(directory=os.path.join(testDir, '.covhtml'))
        else:
            cov.report()

TEST_MODULES = ['test_base', 'test_fields', 'test_save', 'test_queries', 
                'test_update', 'test_delete', 'test_connection']

if __name__ == '__main__':
    verbosity = 1 #Verbosity of output
    failfast = 1 #Exit on first failure/error
    report = 'html' # 'html'|'text'|'', if debug in IDE, set to ''
    testonly = '' #module name, empty for testing all

    #os.environ['WEEDATA_TEST_BACKEND'] = 'mongodb'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'redis'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'pickle'
    #os.environ['WEEDATA_TEST_BACKEND'] = 'datastore'
    
    os.environ['WEEDATA_TEST_VERBOSITY'] = str(verbosity)
    os.environ['WEEDATA_SLOW_TESTS'] = '1' #Run tests that may be slow

    sys.exit(start_test(verbosity, failfast, testonly, report))
