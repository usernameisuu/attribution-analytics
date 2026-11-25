import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import provision_test_database


class ProvisioningTests(unittest.TestCase):
    def test_password_is_required_before_connecting(self):
        config={'ATTRIBUTION_TEST_ADMIN_DATABASE_URL':'postgresql+psycopg://admin:unused@192.168.100.101/postgres'}
        with patch('pathlib.Path.is_file',return_value=True), \
             patch.object(provision_test_database,'dotenv_values',return_value=config), \
             patch.object(provision_test_database,'create_engine') as create:
            with self.assertRaises(SystemExit):
                provision_test_database.main()
            create.assert_not_called()

    def test_role_password_is_safely_quoted_and_not_printed(self):
        password="dummy-'quoted-test-value-1234567890"
        config={'ATTRIBUTION_TEST_ADMIN_DATABASE_URL':'postgresql+psycopg://admin:unused@192.168.100.101/postgres',
                'ATTRIBUTION_TEST_ROLE_PASSWORD':password}
        statements=[]
        class Driver:
            def execute(self, statement): statements.append(statement.as_string())
        class Connection:
            connection=SimpleNamespace(driver_connection=Driver())
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self, statement):
                if 'rolsuper' in str(statement):
                    return SimpleNamespace(one=lambda:SimpleNamespace(rolsuper=True,rolcreatedb=True,rolcreaterole=True))
                return SimpleNamespace(one=lambda:(False,False))
            def exec_driver_sql(self, statement): statements.append(statement)
        class Engine:
            def connect(self): return Connection()
            def dispose(self): pass
        output=io.StringIO()
        with patch('pathlib.Path.is_file',return_value=True), \
             patch.object(provision_test_database,'dotenv_values',return_value=config), \
             patch.object(provision_test_database,'create_engine',return_value=Engine()), redirect_stdout(output):
            provision_test_database.main()
        self.assertIn("dummy-''quoted",statements[0])
        self.assertNotIn(password,output.getvalue())
        self.assertEqual(statements[1],'CREATE DATABASE attribution_test OWNER attribution_test')

    def test_existing_role_or_database_stops_before_creating_anything(self):
        config={'ATTRIBUTION_TEST_ADMIN_DATABASE_URL':'postgresql+psycopg://admin:unused@192.168.100.101/postgres',
                'ATTRIBUTION_TEST_ROLE_PASSWORD':'dummy-long-test-value-1234567890'}
        class Connection:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self, statement):
                if 'rolsuper' in str(statement):
                    return SimpleNamespace(one=lambda:SimpleNamespace(rolsuper=True,rolcreatedb=True,rolcreaterole=True))
                return SimpleNamespace(one=lambda:(True,False))
        class Engine:
            def connect(self): return Connection()
            def dispose(self): pass
        with patch('pathlib.Path.is_file',return_value=True), \
             patch.object(provision_test_database,'dotenv_values',return_value=config), \
             patch.object(provision_test_database,'create_engine',return_value=Engine()):
            with self.assertRaises(SystemExit):
                provision_test_database.main()
