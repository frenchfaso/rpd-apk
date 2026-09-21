import importlib.machinery,importlib.util,pathlib,sys,unittest
loader=importlib.machinery.SourceFileLoader('backend',sys.argv.pop())
spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
class Validation(unittest.TestCase):
    def test_hostname(self):
        for name in ['M10','raspberry-pi','a']:self.assertEqual(m.validate('hostname',name),name)
        for name in ['-bad','bad-','a\nb','../etc/hosts','$(id)','a'*64]:
            with self.assertRaises(ValueError):m.validate('hostname',name)
    def test_password_stdin_contract(self):
        self.assertEqual(m.validate('password','spaces : and $quotes'), 'spaces : and $quotes')
        for value in ['', 'x\nroot:bad', 'x\0y']:
            with self.assertRaises(ValueError):m.validate('password',value)
    def test_timezone(self):
        for value in ['Europe/Rome','Etc/UTC']:m.validate('timezone',value)
        for value in ['/etc/passwd','../etc/passwd','Etc/../../etc/passwd','UTC\n']:
            with self.assertRaises(ValueError):m.validate('timezone',value)
    def test_operations(self):
        for operation in ['autologin','boot','ssh']:
            for value in ['0','1']:m.validate(operation,value)
            with self.assertRaises(ValueError):m.validate(operation,'frenchfaso')
        with self.assertRaises(ValueError):m.validate('shell','id')
unittest.main()
