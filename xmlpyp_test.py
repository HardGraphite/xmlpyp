#!/bin/env python

import io
import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.append(os.path.dirname(__file__))
import xmlpyp


class TestCase(unittest.TestCase):
    def run_pyp(
            self,
            source: str,
            assert_exception: type | None = None,
            assert_result: str | None = None,
    ):
        with io.StringIO() as output_buffer, io.StringIO(source) as source_buffer:
            with xmlpyp.Processor(output_buffer) as processor:
                if assert_exception is not None:
                    with self.assertRaises(assert_exception):
                        processor(source_buffer)
                if assert_result is not None:
                    processor(source_buffer)
                    self.assertEqual(output_buffer.getvalue(), assert_result)


class CorrectTestCases(TestCase):
    def test(self):
        self.run_pyp(
            source=r'''<?xml version="1.0"?>
<?py
def put(x):
    print(x, end='')
?>
<data>
<int> <?py put(10) ?> </int> <str><?py put('Hello, world!\n') ?></str>
<list><?py
put(' '.join(str(i) for i in range(8)))
?></list><?py
for i in range(4):
    put(f'<tag-{i + 1} />\n')
?>
</data>''',
            assert_result=r'''<?xml version="1.0"?>

<data>
<int> 10 </int> <str>Hello, world!
</str>
<list>0 1 2 3 4 5 6 7</list><tag-1 />
<tag-2 />
<tag-3 />
<tag-4 />

</data>'''
        )


class ErrorTestCases(TestCase):
    def test_unterminated_pi(self):
        self.run_pyp(
            source=r'<msg><?py print("Hello, world!")</msg>',
            assert_exception=xmlpyp.XmlError,
        )

    def test_syntax_error(self):
        self.run_pyp(
            source=r'<msg><?py print("Hello, world!?></msg>',
            assert_exception=xmlpyp.PythonError,
        )

    def test_exec_error(self):
        self.run_pyp(
            source=r'<msg><?py print(msg)?></msg>',
            assert_exception=xmlpyp.PythonError,
        )


if __name__ == '__main__':
    unittest.main()
